from __future__ import annotations

import asyncio
import threading
from datetime import datetime, tzinfo
from typing import Protocol

from pydantic import BaseModel

from app.domain import GoogleWorkspaceSnapshot


class GoogleCollector(Protocol):
    configured: bool
    authorized: bool

    def collect(self) -> GoogleWorkspaceSnapshot: ...

    def set_refresh_token(self, refresh_token: str) -> None: ...


class GoogleWorkerState(BaseModel):
    running: bool = False
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error_type: str | None = None


class GoogleWorkspaceRuntime:
    """Keeps Google failures and refresh timing independent from the core dashboard."""

    def __init__(
        self,
        collector: GoogleCollector,
        *,
        refresh_interval_sec: int,
        timezone: tzinfo,
        eager_initial: bool = False,
    ) -> None:
        self._collector = collector
        self._refresh_interval_sec = refresh_interval_sec
        self._timezone = timezone
        self._eager_initial = eager_initial
        self._lock = threading.RLock()
        self._snapshot = GoogleWorkspaceSnapshot(
            configured=collector.configured,
            authorized=collector.authorized,
            refresh_interval_sec=refresh_interval_sec,
        )
        self._state = GoogleWorkerState()
        self._tasks: list[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        if not self._collector.authorized:
            return
        if self._eager_initial:
            await self.refresh()
        else:
            self._tasks.append(
                asyncio.create_task(self.refresh(), name="google-initial-refresh")
            )
        self._ensure_loop()

    async def stop(self) -> None:
        self._stopping.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def authorize(self, refresh_token: str) -> None:
        self._collector.set_refresh_token(refresh_token)
        with self._lock:
            self._snapshot.configured = True
            self._snapshot.authorized = True
        await self.refresh()
        self._ensure_loop()

    def snapshot(self) -> GoogleWorkspaceSnapshot:
        with self._lock:
            return self._snapshot.model_copy(deep=True)

    def health(self) -> dict[str, object]:
        with self._lock:
            snapshot = self._snapshot.model_copy(deep=True)
            state = self._state.model_copy(deep=True)
        if not snapshot.configured:
            status = "disabled"
        elif not snapshot.authorized:
            status = "authorization_required"
        elif state.running and state.last_success_at is None:
            status = "loading"
        elif snapshot.stale or state.last_error_type:
            status = "degraded"
        elif state.last_success_at:
            status = "ok"
        else:
            status = "loading"
        return {
            "status": status,
            "configured": snapshot.configured,
            "authorized": snapshot.authorized,
            "fetched_at": snapshot.fetched_at.isoformat() if snapshot.fetched_at else None,
            "worker": state.model_dump(mode="json"),
        }

    async def refresh(self) -> None:
        self._state.running = True
        try:
            refreshed = await asyncio.to_thread(self._collector.collect)
            with self._lock:
                self._snapshot = refreshed
                self._state.last_success_at = datetime.now(self._timezone)
                self._state.last_error_type = None
        except Exception as exc:
            with self._lock:
                self._snapshot.configured = self._collector.configured
                self._snapshot.authorized = self._collector.authorized
                self._snapshot.stale = True
                self._snapshot.error = "Google 데이터 갱신에 실패했습니다."
                self._state.last_error_at = datetime.now(self._timezone)
                self._state.last_error_type = type(exc).__name__
        finally:
            self._state.running = False

    def _ensure_loop(self) -> None:
        if any(task.get_name() == "google-refresh" and not task.done() for task in self._tasks):
            return
        self._tasks.append(
            asyncio.create_task(self._worker_loop(), name="google-refresh")
        )

    async def _worker_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await asyncio.wait_for(
                    self._stopping.wait(), timeout=self._refresh_interval_sec
                )
            except TimeoutError:
                await self.refresh()
            except asyncio.CancelledError:
                break
