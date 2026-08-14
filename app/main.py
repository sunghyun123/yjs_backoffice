from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse

from app.config import PROJECT_ROOT, Settings, get_settings
from app.domain import DashboardSnapshot
from app.repository import DashboardRepository, ThinkWiseRepository
from app.runtime import DashboardRuntime
from app.security import install_security_middleware
from app.service import DashboardService, DemoRepository


FRONTEND_FILE = PROJECT_ROOT / "경영대시보드_예시화면_v2.html"


def create_app(
    settings: Settings | None = None,
    repository: DashboardRepository | None = None,
) -> FastAPI:
    runtime_settings = settings or get_settings()
    runtime_repository = repository or _make_repository(runtime_settings)
    service = DashboardService(runtime_repository, runtime_settings)
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

    return app


def _make_repository(settings: Settings) -> DashboardRepository:
    if settings.app_demo_mode:
        return DemoRepository(settings)
    return ThinkWiseRepository(settings)


app = create_app()
