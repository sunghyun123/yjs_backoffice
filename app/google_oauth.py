from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from app.config import Settings
from app.google_workspace import GOOGLE_SCOPES
from app.service import DashboardService


FlowFactory = Callable[..., Any]
_ENV_WRITE_LOCK = threading.RLock()


class GoogleOAuthManager:
    """Runs one-time Google consent and stores the refresh token only in `.env`."""

    def __init__(
        self,
        settings: Settings,
        service: DashboardService,
        env_path: Path,
        *,
        flow_factory: FlowFactory | None = None,
    ) -> None:
        self._settings = settings
        self._service = service
        self._env_path = env_path
        self._flow_factory = flow_factory

    @property
    def configured(self) -> bool:
        return self._settings.google_enabled

    def authorization_url(self) -> str:
        if not self.configured:
            raise RuntimeError("Google OAuth is not configured")
        state = self._service.create_google_oauth_state()
        flow = self._flow(state=state)
        url, returned_state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        if returned_state != state:
            self._service.consume_google_oauth_state(state)
            raise RuntimeError("Google OAuth state 생성 결과가 일치하지 않습니다.")
        return str(url)

    def discard_state(self, state: str) -> bool:
        return bool(state) and self._service.consume_google_oauth_state(state)

    def complete(self, state: str, code: str) -> str:
        if not state or not code or not self._service.consume_google_oauth_state(state):
            raise ValueError("유효하지 않거나 만료된 Google OAuth 요청입니다.")
        flow = self._flow(state=state)
        flow.fetch_token(code=code)
        refresh_token = str(flow.credentials.refresh_token or "")
        if not refresh_token:
            raise RuntimeError("Google에서 갱신 토큰을 받지 못했습니다.")
        _write_env_secret(self._env_path, "GOOGLE_REFRESH_TOKEN", refresh_token)
        self._settings.google_refresh_token = SecretStr(refresh_token)
        return refresh_token

    def _flow(self, *, state: str) -> Any:
        if self._flow_factory is None:
            from google_auth_oauthlib.flow import Flow

            factory = Flow.from_client_config
        else:
            factory = self._flow_factory
        client_config = {
            "web": {
                "client_id": self._settings.google_client_id,
                "client_secret": self._settings.google_client_secret.get_secret_value(),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [self._settings.google_redirect_uri],
            }
        }
        flow = factory(client_config, scopes=list(GOOGLE_SCOPES), state=state)
        flow.redirect_uri = self._settings.google_redirect_uri
        return flow


def _write_env_secret(path: Path, key: str, value: str) -> None:
    if not value or "\r" in value or "\n" in value:
        raise ValueError("환경 변수 값이 올바르지 않습니다.")
    with _ENV_WRITE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        replacement = f"{key}={json.dumps(value)}"
        updated: list[str] = []
        found = False
        for line in existing:
            if line.startswith(f"{key}="):
                if not found:
                    updated.append(replacement)
                    found = True
                continue
            updated.append(line)
        if not found:
            if updated and updated[-1]:
                updated.append("")
            updated.append(replacement)

        # Keep the existing Windows ACL by updating the file itself instead of
        # replacing it with a newly created temporary file.
        with path.open("w", encoding="utf-8", newline="\n") as env_file:
            env_file.write("\n".join(updated) + "\n")
            env_file.flush()
            os.fsync(env_file.fileno())
