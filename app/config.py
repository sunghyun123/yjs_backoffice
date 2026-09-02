from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8080, ge=1, le=65535)
    app_demo_mode: bool = True
    app_timezone: str = "Asia/Seoul"
    app_trust_tailscale_headers: bool = False
    app_allowed_tailscale_users: str = ""
    # Backward compatibility for already-deployed single-user environments.
    app_allowed_tailscale_user: str = ""

    db_host: str = "127.0.0.1"
    db_port: int = Field(default=3306, ge=1, le=65535)
    db_user: str = ""
    db_password: SecretStr = SecretStr("")
    db_charset: str = "utf8"
    db_refresh_seconds: int = Field(default=60, ge=30, le=3600)
    work_log_refresh_seconds: int = Field(default=60, ge=60, le=3600)
    thinkwise_index_path: str = ""
    thinkwise_index_max_age_seconds: int = Field(default=180, ge=60, le=3600)

    sqlite_path: Path = Path("data/dashboard.db")
    mail_refresh_seconds: int = Field(default=300, ge=60, le=3600)
    mail_daou_enabled: bool = False
    mail_daou_host: str = "imap.daouoffice.com"
    mail_daou_port: int = Field(default=993, ge=1, le=65535)
    mail_daou_user: str = ""
    mail_daou_password: SecretStr = SecretStr("")
    mail_daou_url: str = "#"
    mail_gmail_enabled: bool = False
    mail_gmail_host: str = "imap.gmail.com"
    mail_gmail_port: int = Field(default=993, ge=1, le=65535)
    mail_gmail_user: str = ""
    mail_gmail_password: SecretStr = SecretStr("")
    mail_gmail_url: str = "https://mail.google.com/"
    mail_naver_enabled: bool = False
    mail_naver_host: str = "imap.naver.com"
    mail_naver_port: int = Field(default=993, ge=1, le=65535)
    mail_naver_user: str = ""
    mail_naver_password: SecretStr = SecretStr("")
    mail_naver_url: str = "https://mail.naver.com/"

    google_enabled: bool = False
    google_refresh_seconds: int = Field(default=60, ge=60, le=3600)
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    google_refresh_token: SecretStr = SecretStr("")
    google_redirect_uri: str = ""
    google_shared_drive_id: str = ""

    @field_validator("app_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @field_validator("db_charset")
    @classmethod
    def enforce_legacy_utf8(cls, value: str) -> str:
        if value.lower() != "utf8":
            raise ValueError("씽크와이즈 DB 연결 문자셋은 utf8이어야 합니다.")
        return "utf8"

    @field_validator("app_host")
    @classmethod
    def enforce_loopback_binding(cls, value: str) -> str:
        if value.strip() != "127.0.0.1":
            raise ValueError("대시보드는 보안을 위해 127.0.0.1에만 바인딩해야 합니다.")
        return "127.0.0.1"

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.app_trust_tailscale_headers and not self.allowed_tailscale_users:
            raise ValueError(
                "APP_TRUST_TAILSCALE_HEADERS=true이면 APP_ALLOWED_TAILSCALE_USERS가 필요합니다."
            )
        if not self.app_demo_mode:
            if not self.db_user.strip() or not self.db_password.get_secret_value():
                raise ValueError("실데이터 모드에는 DB_USER와 DB_PASSWORD가 필요합니다.")
        if self.app_env.strip().lower() == "production":
            if self.app_demo_mode:
                raise ValueError("운영 환경에서는 APP_DEMO_MODE=false여야 합니다.")
            if not self.app_trust_tailscale_headers:
                raise ValueError(
                    "운영 환경에서는 Tailscale 사용자 헤더 검증을 활성화해야 합니다."
                )
            if not self.thinkwise_index_path.strip():
                raise ValueError("운영 환경에서는 THINKWISE_INDEX_PATH가 필요합니다.")
        mail_accounts = (
            (
                "다우오피스",
                self.mail_daou_enabled,
                self.mail_daou_host,
                self.mail_daou_user,
                self.mail_daou_password,
                self.mail_daou_url,
            ),
            (
                "Gmail",
                self.mail_gmail_enabled,
                self.mail_gmail_host,
                self.mail_gmail_user,
                self.mail_gmail_password,
                self.mail_gmail_url,
            ),
            (
                "네이버",
                self.mail_naver_enabled,
                self.mail_naver_host,
                self.mail_naver_user,
                self.mail_naver_password,
                self.mail_naver_url,
            ),
        )
        if self.mail_daou_enabled and "@" not in self.mail_daou_user:
            raise ValueError("다우오피스 메일 사용자는 전체 메일 주소여야 합니다.")
        for label, enabled, host, user, password, mailbox_url in mail_accounts:
            if enabled and (
                not host.strip()
                or not user.strip()
                or not password.get_secret_value()
                or not mailbox_url.lower().startswith("https://")
            ):
                raise ValueError(
                    f"{label} 메일을 활성화하려면 호스트·사용자·비밀번호·HTTPS 웹메일 주소가 필요합니다."
                )
        if self.google_enabled:
            if (
                not self.google_client_id.strip()
                or not self.google_client_secret.get_secret_value()
                or not self.google_redirect_uri.strip()
            ):
                raise ValueError(
                    "Google 연동을 활성화하려면 Client ID·Client Secret·Redirect URI가 필요합니다."
                )
            redirect_uri = self.google_redirect_uri.strip().lower()
            if self.app_env.strip().lower() == "production":
                if not redirect_uri.startswith("https://"):
                    raise ValueError("운영 Google Redirect URI는 HTTPS여야 합니다.")
                if not self.google_shared_drive_id.strip():
                    raise ValueError(
                        "운영 Google 연동에는 GOOGLE_SHARED_DRIVE_ID가 필요합니다."
                    )
            elif not redirect_uri.startswith(
                ("http://127.0.0.1", "http://localhost", "https://")
            ):
                raise ValueError("개발 Google Redirect URI는 localhost HTTP 또는 HTTPS여야 합니다.")
        return self

    @property
    def allowed_tailscale_users(self) -> frozenset[str]:
        values: set[str] = set()
        for raw_value in (
            self.app_allowed_tailscale_users,
            self.app_allowed_tailscale_user,
        ):
            values.update(
                item.strip().lower()
                for item in raw_value.split(",")
                if item.strip()
            )
        return frozenset(values)

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def resolved_sqlite_path(self) -> Path:
        path = self.sqlite_path
        if str(path) == ":memory:":
            return path
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def resolved_thinkwise_index_path(self) -> Path | None:
        raw_path = self.thinkwise_index_path.strip()
        if not raw_path:
            return None
        path = Path(raw_path)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def google_authorized(self) -> bool:
        return self.google_enabled and bool(self.google_refresh_token.get_secret_value())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
