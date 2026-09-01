from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, RedirectResponse

from app.config import PROJECT_ROOT, Settings, get_settings
from app.domain import (
    DashboardSnapshot,
    GoogleWorkspaceSnapshot,
    ProjectMarkUpdate,
    StatusThresholds,
    TodoCreate,
    TodoItem,
)
from app.google_oauth import GoogleOAuthManager
from app.google_runtime import GoogleCollector, GoogleWorkspaceRuntime
from app.google_workspace import DemoGoogleWorkspaceCollector, GoogleWorkspaceCollector
from app.mail import MailAccount, MailCollector
from app.repository import DashboardRepository, ThinkWiseRepository
from app.runtime import DashboardRuntime
from app.security import install_security_middleware
from app.service import DashboardService, DemoRepository
from app.state_store import DashboardStateStore
from app.worklog_index import SQLiteWorkLogIndex


FRONTEND_FILE = PROJECT_ROOT / "경영대시보드_예시화면_v2.html"


def create_app(
    settings: Settings | None = None,
    repository: DashboardRepository | None = None,
    google_collector: GoogleCollector | None = None,
    google_oauth_manager: Any | None = None,
) -> FastAPI:
    runtime_settings = settings or get_settings()
    runtime_repository = repository or _make_repository(runtime_settings)
    state_store = DashboardStateStore(
        runtime_settings.resolved_sqlite_path,
        runtime_settings.timezone,
    )
    service = DashboardService(
        runtime_repository,
        runtime_settings,
        state_store,
        _make_mail_collector(runtime_settings),
    )
    runtime = DashboardRuntime(service, runtime_repository, runtime_settings)
    runtime_google_collector = google_collector or _make_google_collector(runtime_settings)
    google_runtime = GoogleWorkspaceRuntime(
        runtime_google_collector,
        refresh_interval_sec=runtime_settings.google_refresh_seconds,
        timezone=runtime_settings.timezone,
        eager_initial=runtime_settings.app_demo_mode,
    )
    oauth_manager = google_oauth_manager or GoogleOAuthManager(
        runtime_settings,
        service,
        PROJECT_ROOT / ".env",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.dashboard_runtime = runtime
        app.state.google_runtime = google_runtime
        await runtime.start()
        await google_runtime.start()
        try:
            yield
        finally:
            await google_runtime.stop()
            await runtime.stop()

    app = FastAPI(
        title="YJ 경영 대시보드",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    install_security_middleware(app, runtime_settings)

    @app.get("/", include_in_schema=False)
    async def dashboard_page() -> FileResponse:
        return FileResponse(FRONTEND_FILE, media_type="text/html; charset=utf-8")

    @app.get("/api/dashboard", response_model=DashboardSnapshot)
    async def dashboard_data(request: Request) -> DashboardSnapshot:
        dashboard_runtime: DashboardRuntime = request.app.state.dashboard_runtime
        return dashboard_runtime.snapshot()

    @app.get("/api/health")
    async def health(request: Request) -> dict[str, object]:
        dashboard_runtime: DashboardRuntime = request.app.state.dashboard_runtime
        result = dashboard_runtime.health()
        result["google"] = google_runtime.health()
        return result

    @app.get("/api/google", response_model=GoogleWorkspaceSnapshot)
    async def google_data() -> GoogleWorkspaceSnapshot:
        return google_runtime.snapshot()

    @app.get("/api/google/oauth/start", include_in_schema=False)
    async def google_oauth_start() -> RedirectResponse:
        if not oauth_manager.configured:
            raise HTTPException(status_code=503, detail="Google OAuth 설정이 필요합니다.")
        try:
            authorization_url = oauth_manager.authorization_url()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Google OAuth 요청을 시작하지 못했습니다.",
            ) from exc
        return RedirectResponse(authorization_url, status_code=status.HTTP_302_FOUND)

    @app.get("/api/google/oauth/callback", include_in_schema=False)
    async def google_oauth_callback(
        state: str = "",
        code: str = "",
        error: str = "",
    ) -> RedirectResponse:
        if error:
            if not oauth_manager.discard_state(state):
                raise HTTPException(
                    status_code=400,
                    detail="유효하지 않거나 만료된 Google OAuth 요청입니다.",
                )
            return RedirectResponse(
                "/?google=denied#weekly",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        try:
            refresh_token = await asyncio.to_thread(oauth_manager.complete, state, code)
            await google_runtime.authorize(refresh_token)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="Google 계정 연결을 완료하지 못했습니다.",
            ) from exc
        return RedirectResponse(
            "/?google=connected#weekly",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    @app.get("/api/settings", response_model=StatusThresholds)
    async def dashboard_settings() -> StatusThresholds:
        return service.get_thresholds()

    @app.put("/api/settings", response_model=StatusThresholds)
    async def update_dashboard_settings(
        thresholds: StatusThresholds,
    ) -> StatusThresholds:
        service.set_thresholds(thresholds)
        await runtime.refresh_core()
        return service.get_thresholds()

    def require_project(hashfname: str) -> None:
        if not any(
            project.hashfname == hashfname for project in runtime.snapshot().projects
        ):
            raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")

    @app.put(
        "/api/project/{hashfname}/mark",
        response_model=DashboardSnapshot,
    )
    async def update_project_mark(
        hashfname: str,
        payload: ProjectMarkUpdate,
    ) -> DashboardSnapshot:
        require_project(hashfname)
        service.set_mark(hashfname, payload.mark, payload.memo)
        await runtime.refresh_core()
        return runtime.snapshot()

    @app.delete(
        "/api/project/{hashfname}/mark",
        response_model=DashboardSnapshot,
    )
    async def delete_project_mark(hashfname: str) -> DashboardSnapshot:
        require_project(hashfname)
        service.delete_mark(hashfname)
        await runtime.refresh_core()
        return runtime.snapshot()

    @app.get("/api/todos", response_model=list[TodoItem])
    async def list_todos() -> list[TodoItem]:
        return service.list_todos()

    @app.post(
        "/api/todos",
        response_model=TodoItem,
        status_code=status.HTTP_201_CREATED,
    )
    async def add_todo(payload: TodoCreate) -> TodoItem:
        return service.add_todo(payload.text)

    @app.delete("/api/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_todo(todo_id: int) -> Response:
        if not service.delete_todo(todo_id):
            raise HTTPException(status_code=404, detail="할 일을 찾을 수 없습니다.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app


def _make_repository(settings: Settings) -> DashboardRepository:
    if settings.app_demo_mode:
        return DemoRepository(settings)
    index_path = settings.resolved_thinkwise_index_path
    work_log_index = (
        SQLiteWorkLogIndex(
            index_path,
            settings.timezone,
            max_age_seconds=settings.thinkwise_index_max_age_seconds,
        )
        if index_path is not None
        else None
    )
    return ThinkWiseRepository(settings, work_log_index)


def _make_mail_collector(settings: Settings) -> MailCollector:
    accounts: list[MailAccount] = []
    candidates = (
        (
            "daou",
            settings.mail_daou_enabled,
            settings.mail_daou_host,
            settings.mail_daou_port,
            settings.mail_daou_user,
            settings.mail_daou_password.get_secret_value(),
            settings.mail_daou_url,
        ),
        (
            "gmail",
            settings.mail_gmail_enabled,
            settings.mail_gmail_host,
            settings.mail_gmail_port,
            settings.mail_gmail_user,
            settings.mail_gmail_password.get_secret_value(),
            settings.mail_gmail_url,
        ),
        (
            "naver",
            settings.mail_naver_enabled,
            settings.mail_naver_host,
            settings.mail_naver_port,
            settings.mail_naver_user,
            settings.mail_naver_password.get_secret_value(),
            settings.mail_naver_url,
        ),
    )
    for name, enabled, host, port, username, password, mailbox_url in candidates:
        if enabled:
            accounts.append(
                MailAccount(name, host, port, username, password, mailbox_url)
            )
    return MailCollector(
        accounts,
        settings.timezone,
        settings.mail_refresh_seconds,
    )


def _make_google_collector(settings: Settings) -> GoogleCollector:
    if settings.app_demo_mode:
        return DemoGoogleWorkspaceCollector(
            settings.timezone,
            settings.google_refresh_seconds,
        )
    return GoogleWorkspaceCollector(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
        refresh_token=settings.google_refresh_token.get_secret_value(),
        timezone=settings.timezone,
        refresh_interval_sec=settings.google_refresh_seconds,
        configured=settings.google_enabled,
    )
