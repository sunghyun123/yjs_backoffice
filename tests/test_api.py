from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_demo_mode": True,
        "app_trust_tailscale_headers": False,
        "db_refresh_seconds": 60,
        "work_log_refresh_seconds": 300,
        "mail_refresh_seconds": 300,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_dashboard_and_health_are_ready_in_demo_mode() -> None:
    app = create_app(make_settings())
    with TestClient(app) as client:
        dashboard = client.get("/api/dashboard")
        health = client.get("/api/health")

    assert dashboard.status_code == 200
    assert dashboard.headers["cache-control"] == "no-store"
    payload = dashboard.json()
    assert payload["stale"] is False
    assert payload["kpi"]["online_now"] == 4
    assert payload["kpi"]["active_users_30d"] == 7
    assert payload["kpi"]["idle"] == 5
    assert len(payload["recent_edits"]) == 4

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["demo_mode"] is True


def test_dashboard_page_serves_approved_mockup() -> None:
    app = create_app(make_settings())
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "프로젝트 현재 상태" in response.text
    assert "최근 안 읽은 메일" in response.text
    assert "fetch('/api/dashboard'" in response.text
    assert "setInterval(loadDashboard, 60000)" in response.text
    assert "textContent" in response.text


def test_tailscale_identity_is_required_when_enabled() -> None:
    settings = make_settings(
        app_trust_tailscale_headers=True,
        app_allowed_tailscale_user="ceo@example.test",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        denied = client.get("/api/dashboard")
        allowed = client.get(
            "/api/dashboard",
            headers={"Tailscale-User-Login": "ceo@example.test"},
        )

    assert denied.status_code == 403
    assert allowed.status_code == 200
