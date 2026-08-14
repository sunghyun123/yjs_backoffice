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
    app_allowed_tailscale_user: str = ""

    db_host: str = "127.0.0.1"
    db_port: int = Field(default=3306, ge=1, le=65535)
    db_user: str = ""
    db_password: SecretStr = SecretStr("")
    db_charset: str = "utf8"
    db_refresh_seconds: int = Field(default=60, ge=30, le=3600)
    work_log_refresh_seconds: int = Field(default=300, ge=60, le=3600)

    sqlite_path: Path = Path("data/dashboard.db")
    mail_refresh_seconds: int = Field(default=300, ge=60, le=3600)

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

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.app_trust_tailscale_headers and not self.app_allowed_tailscale_user.strip():
            raise ValueError(
                "APP_TRUST_TAILSCALE_HEADERS=true이면 APP_ALLOWED_TAILSCALE_USER가 필요합니다."
            )
        if not self.app_demo_mode:
            if not self.db_user.strip() or not self.db_password.get_secret_value():
                raise ValueError("실데이터 모드에는 DB_USER와 DB_PASSWORD가 필요합니다.")
        return self

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def resolved_sqlite_path(self) -> Path:
        path = self.sqlite_path
        return path if path.is_absolute() else PROJECT_ROOT / path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
