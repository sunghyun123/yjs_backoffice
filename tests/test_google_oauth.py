from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.google_oauth import GoogleOAuthManager


class OAuthStateServiceStub:
    def __init__(self) -> None:
        self.valid = True

    def create_google_oauth_state(self) -> str:
        return "one-time-state"

    def consume_google_oauth_state(self, state: str) -> bool:
        was_valid = self.valid and state == "one-time-state"
        self.valid = False
        return was_valid


class FlowStub:
    redirect_uri = ""

    def __init__(self) -> None:
        self.credentials = SimpleNamespace(refresh_token="refresh-secret")
        self.code = ""

    def authorization_url(self, **kwargs: object) -> tuple[str, str]:
        assert kwargs["access_type"] == "offline"
        assert kwargs["prompt"] == "consent"
        return (
            "https://accounts.google.com/o/oauth2/auth?state=one-time-state",
            "one-time-state",
        )

    def fetch_token(self, *, code: str) -> None:
        self.code = code


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_demo_mode=True,
        google_enabled=True,
        google_client_id="client-id",
        google_client_secret="client-secret",
        google_redirect_uri="https://dashboard.example/api/google/oauth/callback",
    )


def test_oauth_refresh_token_is_written_only_to_env(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("DB_PASSWORD=preserved\nGOOGLE_REFRESH_TOKEN=old\n", encoding="utf-8")
    service = OAuthStateServiceStub()
    flow = FlowStub()

    def flow_factory(*_args: object, **_kwargs: object) -> FlowStub:
        return flow

    manager = GoogleOAuthManager(
        make_settings(),
        service,  # type: ignore[arg-type]
        env_path,
        flow_factory=flow_factory,
    )

    assert manager.authorization_url().startswith("https://accounts.google.com/")
    assert manager.complete("one-time-state", "authorization-code") == "refresh-secret"
    content = env_path.read_text(encoding="utf-8")
    assert "DB_PASSWORD=preserved" in content
    assert 'GOOGLE_REFRESH_TOKEN="refresh-secret"' in content
    assert flow.code == "authorization-code"
    assert list(tmp_path.glob("*.tmp")) == []


def test_oauth_state_is_single_use(tmp_path: Path) -> None:
    service = OAuthStateServiceStub()
    manager = GoogleOAuthManager(
        make_settings(),
        service,  # type: ignore[arg-type]
        tmp_path / ".env",
        flow_factory=lambda *_args, **_kwargs: FlowStub(),
    )

    assert manager.complete("one-time-state", "code") == "refresh-secret"
    with pytest.raises(ValueError, match="유효하지 않거나 만료"):
        manager.complete("one-time-state", "replay")
