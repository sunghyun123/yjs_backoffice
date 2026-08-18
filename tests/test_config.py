from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_demo_mode": True,
        "app_host": "127.0.0.1",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_dashboard_cannot_bind_to_lan_or_public_interfaces() -> None:
    with pytest.raises(ValidationError, match="127.0.0.1"):
        make_settings(app_host="0.0.0.0")


def test_thinkwise_activity_defaults_to_one_minute_and_three_minute_stale_limit() -> None:
    settings = make_settings()

    assert settings.work_log_refresh_seconds == 60
    assert settings.thinkwise_index_max_age_seconds == 180


def test_production_requires_real_data_and_tailscale_identity_validation() -> None:
    with pytest.raises(ValidationError, match="APP_DEMO_MODE=false"):
        make_settings(app_env="production")

    with pytest.raises(ValidationError, match="Tailscale 사용자 헤더"):
        make_settings(
            app_env="production",
            app_demo_mode=False,
            db_user="readonly",
            db_password="secret",
        )


def test_valid_production_settings_are_accepted() -> None:
    settings = make_settings(
        app_env="production",
        app_demo_mode=False,
        app_trust_tailscale_headers=True,
        app_allowed_tailscale_user="ceo@example.test",
        db_user="readonly",
        db_password="secret",
        thinkwise_index_path="data/wiki_index.db",
    )

    assert settings.app_host == "127.0.0.1"
    assert settings.app_demo_mode is False


def test_production_requires_shared_work_log_index() -> None:
    with pytest.raises(ValidationError, match="THINKWISE_INDEX_PATH"):
        make_settings(
            app_env="production",
            app_demo_mode=False,
            app_trust_tailscale_headers=True,
            app_allowed_tailscale_user="ceo@example.test",
            db_user="readonly",
            db_password="secret",
        )


def test_enabled_mail_requires_https_mailbox_url() -> None:
    with pytest.raises(ValidationError, match="HTTPS 웹메일 주소"):
        make_settings(
            mail_daou_enabled=True,
            mail_daou_user="mail@example.test",
            mail_daou_password="secret",
            mail_daou_url="#",
        )


def test_enabled_daou_mail_requires_full_email_address() -> None:
    with pytest.raises(ValueError, match="전체 메일 주소"):
        make_settings(
            mail_daou_enabled=True,
            mail_daou_user="ceo",
            mail_daou_password="secret",
            mail_daou_url="https://mail.example.test/",
        )
