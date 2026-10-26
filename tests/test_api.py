from datetime import datetime

from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Settings
from app.domain import GoogleWorkspaceSnapshot
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
        google = client.get("/api/google")

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
    assert health.json()["google"]["status"] == "ok"
    assert google.status_code == 200
    assert google.json()["drive_scope"] == "shared"
    assert len(google.json()["events"]) == 2
    assert len(google.json()["files"]) == 2


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
    assert 'class="panel mail-panel"' in response.text
    assert 'id="todoInput"' in response.text
    assert 'id="calendarList"' in response.text
    assert 'id="driveList"' in response.text
    assert 'id="googleConnectLink"' in response.text
    assert "fetch('/api/google'" in response.text
    assert 'class="executive-weekly"' in response.text
    assert 'role="tablist"' in response.text
    assert 'id="googleTab"' in response.text
    assert 'id="thinkwiseTab"' in response.text
    assert 'id="googlePanel"' in response.text
    assert 'id="thinkwisePanel"' in response.text
    assert 'aria-selected="true"' in response.text
    assert 'id="thinkwisePanel" role="tabpanel" aria-labelledby="thinkwiseTab" hidden' in response.text
    assert "activateDashboardTab('google')" in response.text
    assert "회사 공유 Drive 최근 수정 파일" in response.text
    assert "fetch('/api/todos'" in response.text
    assert "완료하면 목록에서 자동으로 정리됩니다." in response.text
    assert "(mail.items || []).slice(0, 10)" in response.text
    # core.autocrlf=true 체크아웃에서는 본문이 CRLF 라 여러 줄 단언은 정규화 후 비교한다.
    assert ".mail-list {\n    display: grid;\n    grid-template-columns: repeat(2, minmax(0, 1fr));" in response.text.replace("\r\n", "\n")


def test_tailscale_identity_is_required_when_enabled() -> None:
    settings = make_settings(
        app_trust_tailscale_headers=True,
        app_allowed_tailscale_users="maintainer@example.test,ceo@example.test",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        denied = client.get("/api/dashboard")
        maintainer_allowed = client.get(
            "/api/dashboard",
            headers={"Tailscale-User-Login": "maintainer@example.test"},
        )
        ceo_allowed = client.get(
            "/api/dashboard",
            headers={"Tailscale-User-Login": "ceo@example.test"},
        )
        unknown_denied = client.get(
            "/api/dashboard",
            headers={"Tailscale-User-Login": "unknown@example.test"},
        )

    assert denied.status_code == 403
    assert maintainer_allowed.status_code == 200
    assert ceo_allowed.status_code == 200
    assert unknown_denied.status_code == 403
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


def test_todos_are_shared_persisted_and_removed_on_completion(tmp_path) -> None:
    settings = make_settings(sqlite_path=tmp_path / "dashboard.db")
    first_app = create_app(settings)
    with TestClient(first_app) as client:
        created = client.post("/api/todos", json={"text": "  주간 보고 확인  "})
        listed = client.get("/api/todos")

    assert created.status_code == 201
    assert created.json()["text"] == "주간 보고 확인"
    todo_id = created.json()["id"]
    assert listed.json() == [created.json()]

    reopened_app = create_app(settings)
    with TestClient(reopened_app) as client:
        persisted = client.get("/api/todos")
        completed = client.delete(f"/api/todos/{todo_id}")
        empty = client.get("/api/todos")
        missing = client.delete(f"/api/todos/{todo_id}")

    assert persisted.json() == [created.json()]
    assert completed.status_code == 204
    assert completed.content == b""
    assert empty.json() == []
    assert missing.status_code == 404


def test_todo_input_is_validated() -> None:
    app = create_app(make_settings())
    with TestClient(app) as client:
        blank = client.post("/api/todos", json={"text": "   "})
        too_long = client.post("/api/todos", json={"text": "가" * 121})

    assert blank.status_code == 422
    assert too_long.status_code == 422


def test_todo_list_is_shared_by_all_allowed_tailscale_accounts() -> None:
    settings = make_settings(
        app_trust_tailscale_headers=True,
        app_allowed_tailscale_users="maintainer@example.test,ceo@example.test",
    )
    app = create_app(settings)
    maintainer = {
        "Tailscale-User-Login": "maintainer@example.test",
        "Origin": "http://testserver",
    }
    ceo = {"Tailscale-User-Login": "ceo@example.test"}
    with TestClient(app) as client:
        created = client.post(
            "/api/todos",
            json={"text": "공용 목록"},
            headers=maintainer,
        )
        listed = client.get("/api/todos", headers=ceo)

    assert created.status_code == 201
    assert listed.status_code == 200
    assert listed.json() == [created.json()]


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


class GoogleCollectorStub:
    configured = True
    authorized = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def set_refresh_token(self, refresh_token: str) -> None:
        self.authorized = bool(refresh_token)

    def collect(self) -> GoogleWorkspaceSnapshot:
        return GoogleWorkspaceSnapshot(
            configured=True,
            authorized=self.authorized,
            fetched_at=datetime.now(self.settings.timezone),
        )


class GoogleOAuthManagerStub:
    configured = True

    def __init__(self) -> None:
        self.completed: tuple[str, str] | None = None
        self.discarded = ""

    def authorization_url(self) -> str:
        return "https://accounts.google.com/o/oauth2/auth?state=test-state"

    def complete(self, state: str, code: str) -> str:
        self.completed = (state, code)
        return "refresh-token"

    def discard_state(self, state: str) -> bool:
        self.discarded = state
        return state == "test-state"


def test_google_oauth_routes_connect_runtime_without_restart() -> None:
    settings = make_settings()
    collector = GoogleCollectorStub(settings)
    oauth = GoogleOAuthManagerStub()
    app = create_app(
        settings,
        google_collector=collector,
        google_oauth_manager=oauth,
    )

    with TestClient(app) as client:
        start = client.get("/api/google/oauth/start", follow_redirects=False)
        callback = client.get(
            "/api/google/oauth/callback?state=test-state&code=test-code",
            follow_redirects=False,
        )
        google = client.get("/api/google")

    assert start.status_code == 302
    assert start.headers["location"].startswith("https://accounts.google.com/")
    assert callback.status_code == 303
    assert callback.headers["location"] == "/?google=connected#weekly"
    assert oauth.completed == ("test-state", "test-code")
    assert google.json()["authorized"] is True


def test_google_oauth_start_is_unavailable_without_configuration() -> None:
    app = create_app(make_settings())

    with TestClient(app) as client:
        response = client.get("/api/google/oauth/start")

    assert response.status_code == 503
    assert response.json()["detail"] == "Google OAuth 설정이 필요합니다."


def test_google_oauth_denial_still_requires_valid_state() -> None:
    settings = make_settings()
    oauth = GoogleOAuthManagerStub()
    app = create_app(
        settings,
        google_collector=GoogleCollectorStub(settings),
        google_oauth_manager=oauth,
    )

    with TestClient(app) as client:
        invalid = client.get(
            "/api/google/oauth/callback?state=forged&error=access_denied",
            follow_redirects=False,
        )
        denied = client.get(
            "/api/google/oauth/callback?state=test-state&error=access_denied",
            follow_redirects=False,
        )

    assert invalid.status_code == 400
    assert denied.status_code == 303
    assert denied.headers["location"] == "/?google=denied#weekly"
