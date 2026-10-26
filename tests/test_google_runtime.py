from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from app.domain import GoogleWorkspaceSnapshot
from app.google_runtime import GoogleWorkspaceRuntime


class CollectorStub:
    def __init__(self, result: GoogleWorkspaceSnapshot, *, authorized: bool = True) -> None:
        self.result = result
        self.configured = True
        self.authorized = authorized
        self.fail = False

    def collect(self) -> GoogleWorkspaceSnapshot:
        if self.fail:
            raise TimeoutError("external timeout")
        return self.result

    def set_refresh_token(self, refresh_token: str) -> None:
        self.authorized = bool(refresh_token)


def test_google_refresh_failure_preserves_last_successful_snapshot() -> None:
    timezone = ZoneInfo("Asia/Seoul")
    fetched_at = datetime.now(timezone)
    successful = GoogleWorkspaceSnapshot(
        configured=True,
        authorized=True,
        fetched_at=fetched_at,
    )
    collector = CollectorStub(successful)
    runtime = GoogleWorkspaceRuntime(
        collector,
        refresh_interval_sec=300,
        timezone=timezone,
    )

    asyncio.run(runtime.refresh())
    collector.fail = True
    asyncio.run(runtime.refresh())

    snapshot = runtime.snapshot()
    assert snapshot.fetched_at == fetched_at
    assert snapshot.stale is True
    assert snapshot.error == "Google 데이터 갱신에 실패했습니다."
    assert runtime.health()["status"] == "degraded"


def test_google_runtime_can_be_authorized_without_restarting_app() -> None:
    timezone = ZoneInfo("Asia/Seoul")
    collector = CollectorStub(
        GoogleWorkspaceSnapshot(
            configured=True,
            authorized=True,
            fetched_at=datetime.now(timezone),
        ),
        authorized=False,
    )
    runtime = GoogleWorkspaceRuntime(
        collector,
        refresh_interval_sec=300,
        timezone=timezone,
    )

    async def exercise() -> None:
        await runtime.start()
        assert runtime.health()["status"] == "authorization_required"
        await runtime.authorize("refresh-token")
        assert runtime.health()["status"] == "ok"
        await runtime.stop()

    asyncio.run(exercise())
