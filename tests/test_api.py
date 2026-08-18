from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Settings
from app.main import create_app


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_demo_mode": True,
        "app_trust_tailscale_headers": False,
        "db_refresh_seconds": 60,
        "work_log_refresh_seconds": 300,
        "mail_refresh_seconds": 300,
        "sqlite_path": ":memory:",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_module_uses_an_explicit_application_factory() -> None:
    assert callable(main_module.create_app)
    assert not hasattr(main_module, "app")


def test_dashboard_and_health_are_ready_in_demo_mode() -> None:
    app = create_app(make_settings())
    with TestClient(app) as client:
        dashboard = client.get("/api/dashboard")
        health = client.get("/api/health")

    assert dashboard.status_code == 200
    assert dashboard.headers["cache-control"] == "no-store"
    assert dashboard.headers["x-content-type-options"] == "nosniff"
    assert dashboard.headers["x-frame-options"] == "DENY"
    assert dashboard.headers["referrer-policy"] == "no-referrer"
    assert dashboard.headers["content-security-policy"].startswith("default-src 'self'")
    assert "access-control-allow-origin" not in dashboard.headers
    assert "strict-transport-security" not in dashboard.headers
    payload = dashboard.json()
    assert payload["stale"] is False
    assert payload["kpi"]["online_now"] == 4
    assert payload["kpi"]["active_users_30d"] == 7
    assert payload["kpi"]["idle"] == 5
    assert len(payload["recent_edits"]) == 4
    assert payload["projects"][0]["creator"]
    assert "owner" not in payload["projects"][0]

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["demo_mode"] is True


def test_dashboard_page_serves_approved_mockup() -> None:
    app = create_app(make_settings())
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"
    assert "access-control-allow-origin" not in response.headers
    assert "프로젝트 현재 상태" in response.text
    assert "최근 안 읽은 메일" in response.text
    assert "fetch('/api/dashboard'" in response.text
    assert "setInterval(loadDashboard, 60000)" in response.text
    assert "textContent" in response.text
    assert "innerHTML" not in response.text
    assert "메일 갱신 실패" in response.text
    assert "settings.online_minutes" in response.text
    assert "user.project || '프로젝트 미확인'" in response.text
    assert "health.source?.last_sync_at" in response.text
    assert 'data-filter="current" aria-pressed="true"' in response.text
    assert "let activeFilter = 'current'" in response.text
    assert "showInitialLoadingState()" in response.text
    assert "row.dataset.status !== 'dormant' || Boolean(query)" in response.text
    assert 'id="showAllProjects"' in response.text
    assert 'id="mailboxLink"' in response.text


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
    assert denied.headers["cache-control"] == "no-store"
    assert denied.headers["x-content-type-options"] == "nosniff"
    assert denied.headers["x-frame-options"] == "DENY"
    assert denied.headers["referrer-policy"] == "no-referrer"
    assert denied.headers["content-security-policy"].startswith("default-src 'self'")
    assert denied.headers["strict-transport-security"] == "max-age=31536000"
    assert "access-control-allow-origin" not in denied.headers


def test_tailscale_protected_state_change_requires_same_origin() -> None:
    settings = make_settings(
        app_trust_tailscale_headers=True,
        app_allowed_tailscale_user="ceo@example.test",
    )
    app = create_app(settings)
    identity = {"Tailscale-User-Login": "ceo@example.test"}
    with TestClient(app) as client:
        missing_origin = client.put(
            "/api/project/demo-001/mark",
            json={"mark": "done"},
            headers=identity,
        )
        allowed = client.put(
            "/api/project/demo-001/mark",
            json={"mark": "done"},
            headers={**identity, "Origin": "http://testserver"},
        )
        allowed_through_tls_proxy = client.put(
            "/api/project/demo-001/mark",
            json={"mark": "done"},
            headers={
                **identity,
                "Host": "yj-dashboard.example.ts.net",
                "X-Forwarded-Host": "yj-dashboard.example.ts.net",
                "Origin": "https://yj-dashboard.example.ts.net",
            },
        )
        rejected_lookalike = client.put(
            "/api/project/demo-001/mark",
            json={"mark": "done"},
            headers={
                **identity,
                "Host": "yj-dashboard.example.ts.net",
                "Origin": "https://yj-dashboard.example.ts.net.evil.test",
            },
        )

    assert missing_origin.status_code == 403
    assert allowed.status_code == 200
    assert allowed_through_tls_proxy.status_code == 200
    assert rejected_lookalike.status_code == 403


def test_project_mark_and_settings_are_persisted_and_applied(tmp_path) -> None:
    settings = make_settings(sqlite_path=tmp_path / "dashboard.db")
    app = create_app(settings)
    with TestClient(app) as client:
        marked = client.put(
            "/api/project/demo-006/mark",
            json={"mark": "done", "memo": "대표 확인"},
        )
        updated_settings = client.put(
            "/api/settings",
            json={
                "active_days": 5,
                "idle_days": 10,
                "dormant_days": 20,
                "online_minutes": 30,
            },
        )
        dashboard = client.get("/api/dashboard")
        restored = client.delete("/api/project/demo-006/mark")

    assert marked.status_code == 200
    marked_project = next(
        item for item in marked.json()["projects"] if item["hashfname"] == "demo-006"
    )
    assert marked_project["mark"] == "done"
    assert marked_project["current_status"] == "done"
    assert updated_settings.status_code == 200
    assert updated_settings.json()["online_minutes"] == 30
    dashboard_project = next(
        item for item in dashboard.json()["projects"] if item["hashfname"] == "demo-006"
    )
    assert dashboard_project["auto_status"] == "dormant"
    restored_project = next(
        item for item in restored.json()["projects"] if item["hashfname"] == "demo-006"
    )
    assert restored_project["mark"] is None
    assert restored_project["current_status"] == "dormant"


def test_unknown_project_mark_is_rejected() -> None:
    app = create_app(make_settings())
    with TestClient(app) as client:
        response = client.put(
            "/api/project/not-found/mark",
            json={"mark": "done"},
        )

    assert response.status_code == 404


def test_state_changes_reject_cross_origin_requests() -> None:
    app = create_app(make_settings())
    with TestClient(app) as client:
        response = client.put(
            "/api/project/demo-001/mark",
            json={"mark": "done"},
            headers={"Origin": "https://untrusted.example"},
        )

    assert response.status_code == 403
