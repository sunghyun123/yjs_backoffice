from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timedelta
from typing import cast

from app.config import Settings
from app.domain import DashboardSnapshot, MailSnapshot, RecentEdit
from app.repository import DashboardRepository
from app.runtime import DashboardRuntime
from app.service import DashboardService


class MailServiceStub:
    def __init__(self, result: MailSnapshot) -> None:
        self.result = result

    def load_mail(self) -> MailSnapshot:
        return self.result


class HealthyRepositoryStub:
    def source_health(self) -> dict[str, object]:
        return {"mode": "test", "healthy": True}


class BlockingCoreServiceStub:
    def __init__(self, result: DashboardSnapshot) -> None:
        self.result = result
        self.started = threading.Event()
        self.release = threading.Event()

    def load_core(self) -> DashboardSnapshot:
        self.started.set()
        self.release.wait(timeout=5)
        return self.result


def test_mail_refresh_failure_preserves_last_successful_snapshot() -> None:
    settings = Settings(
        _env_file=None,
        app_demo_mode=False,
        db_user="readonly",
        db_password="secret",
    )
    failed = MailSnapshot(stale=True, error="1개 메일 계정 갱신 실패")
    service = MailServiceStub(failed)
    runtime = DashboardRuntime(
        cast(DashboardService, service),
        cast(DashboardRepository, object()),
        settings,
    )
    fetched_at = datetime.now(settings.timezone) - timedelta(minutes=7)
    runtime._snapshot.mail = MailSnapshot(  # noqa: SLF001
        fetched_at=fetched_at,
        unread_total=8,
        unread_by_account={"daou": 8},
    )

    asyncio.run(runtime.refresh_mail())
    result = runtime.snapshot().mail

    assert result.stale is True
    assert result.error == "1개 메일 계정 갱신 실패"
    assert result.fetched_at == fetched_at
    assert result.unread_total == 8
    assert result.unread_by_account == {"daou": 8}


def test_health_requires_a_current_recent_edits_worker() -> None:
    settings = Settings(_env_file=None, app_demo_mode=True)
    runtime = DashboardRuntime(
        cast(DashboardService, object()),
        cast(DashboardRepository, HealthyRepositoryStub()),
        settings,
    )
    now = datetime.now(settings.timezone)
    runtime._snapshot.stale = False  # noqa: SLF001
    runtime._states["thinkwise"].last_success_at = now  # noqa: SLF001

    assert runtime.health()["status"] == "degraded"

    runtime._states["recent_edits"].last_success_at = now  # noqa: SLF001
    assert runtime.health()["status"] == "ok"

    runtime._states["recent_edits"].last_error_at = now + timedelta(seconds=1)  # noqa: SLF001
    assert runtime.health()["status"] == "degraded"

    runtime._states["recent_edits"].last_success_at = now + timedelta(seconds=2)  # noqa: SLF001
    assert runtime.health()["status"] == "ok"


def test_core_refresh_does_not_overwrite_newer_independent_sections() -> None:
    settings = Settings(
        _env_file=None,
        app_demo_mode=False,
        db_user="readonly",
        db_password="secret",
    )
    now = datetime.now(settings.timezone)
    service = BlockingCoreServiceStub(DashboardSnapshot(generated_at=now))
    runtime = DashboardRuntime(
        cast(DashboardService, service),
        cast(DashboardRepository, HealthyRepositoryStub()),
        settings,
    )
    recent = RecentEdit(
        at=now,
        who="사용자",
        gubun="EDIT",
        detail="동시에 반영된 최근 변경",
    )
    mail = MailSnapshot(fetched_at=now, unread_total=3)

    async def exercise() -> None:
        task = asyncio.create_task(runtime.refresh_core())
        assert await asyncio.to_thread(service.started.wait, 5)
        runtime._snapshot.recent_edits = [recent]  # noqa: SLF001
        runtime._snapshot.mail = mail  # noqa: SLF001
        service.release.set()
        await task

    asyncio.run(exercise())
    snapshot = runtime.snapshot()

    assert snapshot.recent_edits == [recent]
    assert snapshot.mail == mail
