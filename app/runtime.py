from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.config import Settings
from app.domain import DashboardSnapshot, MailSnapshot, RecentEdit
from app.repository import DashboardRepository
from app.service import DashboardService


class WorkerState(BaseModel):
    name: str
    interval_seconds: int
    running: bool = False
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error_type: str | None = None


class DashboardRuntime:
    """Owns the in-memory snapshot and the two independent refresh loops."""

    def __init__(
        self,
        service: DashboardService,
        repository: DashboardRepository,
        settings: Settings,
    ) -> None:
        self._service = service
        self._repository = repository
        self._settings = settings
        self._lock = threading.RLock()
        self._snapshot = DashboardSnapshot(
            generated_at=datetime.now(settings.timezone),
            stale=True,
            error="초기 데이터를 불러오는 중입니다.",
            mail=MailSnapshot(refresh_interval_sec=settings.mail_refresh_seconds),
        )
        self._states = {
            "thinkwise": WorkerState(
                name="thinkwise", interval_seconds=settings.db_refresh_seconds
            ),
            "recent_edits": WorkerState(
                name="recent_edits", interval_seconds=settings.work_log_refresh_seconds
            ),
            "mail": WorkerState(name="mail", interval_seconds=settings.mail_refresh_seconds),
        }
        self._tasks: list[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        await self.refresh_recent_edits()
        await self.refresh_core()
        self._tasks = [
            asyncio.create_task(
                self._worker_loop(
                    "thinkwise", self._settings.db_refresh_seconds, self.refresh_core
                ),
                name="thinkwise-refresh",
            ),
            asyncio.create_task(
                self._worker_loop(
                    "recent_edits",
                    self._settings.work_log_refresh_seconds,
                    self.refresh_recent_edits,
                ),
                name="recent-edits-refresh",
            ),
        ]

    async def stop(self) -> None:
        self._stopping.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        await asyncio.to_thread(self._repository.close)

    def snapshot(self) -> DashboardSnapshot:
        with self._lock:
            return self._snapshot.model_copy(deep=True)

    def health(self) -> dict[str, Any]:
        with self._lock:
            states = {
                name: state.model_copy(deep=True).model_dump(mode="json")
                for name, state in self._states.items()
            }
            snapshot = self._snapshot.model_copy(deep=True)
        core_ready = states["thinkwise"]["last_success_at"] is not None
        return {
            "status": "ok" if core_ready and not snapshot.stale else "degraded",
            "demo_mode": self._settings.app_demo_mode,
            "generated_at": snapshot.generated_at.isoformat(),
            "stale": snapshot.stale,
            "workers": states,
        }

    async def refresh_core(self) -> None:
        state = self._states["thinkwise"]
        state.running = True
        try:
            with self._lock:
                recent_edits = self._snapshot.recent_edits.copy()
                mail = self._snapshot.mail.model_copy(deep=True)
            refreshed = await asyncio.to_thread(
                self._service.load_core, recent_edits=recent_edits
            )
            if not self._settings.app_demo_mode:
                refreshed.mail = mail
            with self._lock:
                self._snapshot = refreshed
                self._record_success(state)
        except Exception as exc:
            with self._lock:
                self._snapshot.stale = True
                self._snapshot.error = "씽크와이즈 데이터 갱신에 실패했습니다."
                self._record_failure(state, exc)
        finally:
            state.running = False

    async def refresh_recent_edits(self) -> None:
        state = self._states["recent_edits"]
        state.running = True
        try:
            recent_edits: list[RecentEdit] = await asyncio.to_thread(
                self._service.load_recent_edits
            )
            with self._lock:
                self._snapshot.recent_edits = recent_edits
                self._record_success(state)
        except Exception as exc:
            with self._lock:
                self._record_failure(state, exc)
        finally:
            state.running = False

    async def _worker_loop(
        self,
        name: str,
        interval_seconds: int,
        callback: Any,
    ) -> None:
        while not self._stopping.is_set():
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=interval_seconds)
            except TimeoutError:
                await callback()
            except asyncio.CancelledError:
                break

    def _record_success(self, state: WorkerState) -> None:
        state.last_success_at = datetime.now(self._settings.timezone)
        state.last_error_type = None

    def _record_failure(self, state: WorkerState, error: Exception) -> None:
        state.last_error_at = datetime.now(self._settings.timezone)
        state.last_error_type = type(error).__name__
