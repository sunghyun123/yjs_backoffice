from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.domain import (
    OnlineUser,
    Project,
    StatusThresholds,
    calculate_kpi,
    classify_project,
    current_status,
    idle_project_list,
)


@pytest.mark.parametrize(
    ("idle_days", "expected"),
    [
        (0, "active"),
        (7, "active"),
        (8, "slowing"),
        (13, "slowing"),
        (14, "idle"),
        (29, "idle"),
        (30, "dormant"),
    ],
)
def test_classify_project_boundaries(idle_days: int, expected: str) -> None:
    assert classify_project(idle_days, StatusThresholds()) == expected


def test_manual_mark_overrides_and_cancel_restores_auto() -> None:
    assert current_status("active", "done") == "done"
    assert current_status("active", None) == "active"


def test_completed_project_is_removed_from_active_and_idle_lists() -> None:
    now = datetime(2026, 8, 14, tzinfo=ZoneInfo("Asia/Seoul"))
    projects = [
        Project(
            hashfname="active-done",
            title="완료 처리된 최근 프로젝트",
            last_touch=now,
            idle_days=0,
            auto_status="active",
            mark="done",
            current_status="done",
        ),
        Project(
            hashfname="idle",
            title="확인할 프로젝트",
            last_touch=now,
            idle_days=20,
            auto_status="idle",
            current_status="idle",
        ),
    ]
    online = [OnlineUser(user_id="u1", name="사용자", at=now)]

    kpi = calculate_kpi(projects, online, active_users_30d=7)

    assert kpi.active == 0
    assert kpi.done == 1
    assert kpi.idle == 1
    assert [item.hashfname for item in idle_project_list(projects)] == ["idle"]


def test_thresholds_must_be_strictly_ordered() -> None:
    with pytest.raises(ValueError):
        StatusThresholds(active_days=14, idle_days=14, dormant_days=30)
