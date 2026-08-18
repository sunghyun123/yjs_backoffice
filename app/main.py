from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from app.config import PROJECT_ROOT, Settings, get_settings
from app.domain import DashboardSnapshot, ProjectMarkUpdate, StatusThresholds
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

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.dashboard_runtime = runtime
        await runtime.start()
        try:
            yield
        finally:
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
        return dashboard_runtime.health()

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
