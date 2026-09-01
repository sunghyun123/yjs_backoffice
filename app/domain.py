from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


AutomaticStatus = Literal["active", "slowing", "idle", "dormant"]
ManualStatus = Literal["running", "done", "hold"]
CurrentStatus = Literal["active", "slowing", "idle", "dormant", "running", "done", "hold"]


class StatusThresholds(BaseModel):
    active_days: int = Field(default=7, ge=0)
    idle_days: int = Field(default=14, ge=1)
    dormant_days: int = Field(default=30, ge=2)
    online_minutes: int = Field(default=15, ge=1, le=1440)

    def model_post_init(self, __context: object) -> None:
        if not self.active_days < self.idle_days < self.dormant_days:
            raise ValueError("상태 기준일은 active < idle < dormant 순서여야 합니다.")


class ProjectMarkUpdate(BaseModel):
    mark: ManualStatus
    memo: str = Field(default="", max_length=500)


class TodoCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=120)


class TodoItem(BaseModel):
    id: int = Field(ge=1)
    text: str
    created_at: datetime


class GoogleCalendarEvent(BaseModel):
    id: str
    title: str
    starts_at: datetime | None = None
    start_date: date | None = None
    ends_at: datetime | None = None
    end_date: date | None = None
    all_day: bool = False
    dday: int


class GoogleDriveFile(BaseModel):
    id: str
    name: str
    mime_type: str
    kind: str
    modified_at: datetime
    open_url: str


class GoogleWorkspaceSnapshot(BaseModel):
    configured: bool = False
    authorized: bool = False
    refresh_interval_sec: int = 300
    fetched_at: datetime | None = None
    stale: bool = False
    error: str | None = None
    week_start: date | None = None
    week_end: date | None = None
    events: list[GoogleCalendarEvent] = Field(default_factory=list)
    files: list[GoogleDriveFile] = Field(default_factory=list)


class Project(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hashfname: str
    title: str
    creator: str | None = None
    members: int = 0
    tree_cnt: int = 0
    last_touch: datetime
    idle_days: int = Field(ge=0)
    auto_status: AutomaticStatus
    mark: ManualStatus | None = None
    current_status: CurrentStatus


class IdleProject(BaseModel):
    hashfname: str
    title: str
    creator: str | None = None
    members: int = 0
    last_touch: datetime
    idle_days: int = Field(ge=0)


class RecentEdit(BaseModel):
    at: datetime
    who: str
    gubun: Literal["ADD", "EDIT", "DEL", "MOVE", "PASTE", "LINK"]
    detail: str
    project: str | None = None


class OnlineUser(BaseModel):
    user_id: str
    name: str
    project: str | None = None
    at: datetime


class MailItem(BaseModel):
    account: Literal["daou", "gmail", "naver"]
    sender: str
    subject: str
    at: datetime | None = None
    mailbox_url: str


class MailSnapshot(BaseModel):
    refresh_interval_sec: int = 300
    fetched_at: datetime | None = None
    stale: bool = False
    error: str | None = None
    unread_total: int = 0
    unread_by_account: dict[str, int] = Field(default_factory=dict)
    items: list[MailItem] = Field(default_factory=list)


class DashboardKpi(BaseModel):
    online_now: int = 0
    active_users_30d: int = 0
    active: int = 0
    slowing: int = 0
    idle: int = 0
    dormant: int = 0
    running: int = 0
    done: int = 0
    hold: int = 0
    total_projects: int = 0


class DashboardSnapshot(BaseModel):
    generated_at: datetime
    stale: bool = False
    error: str | None = None
    kpi: DashboardKpi = Field(default_factory=DashboardKpi)
    idle_projects: list[IdleProject] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    recent_edits: list[RecentEdit] = Field(default_factory=list)
    online_users: list[OnlineUser] = Field(default_factory=list)
    mail: MailSnapshot = Field(default_factory=MailSnapshot)


def classify_project(idle_days: int, thresholds: StatusThresholds) -> AutomaticStatus:
    if idle_days <= thresholds.active_days:
        return "active"
    if idle_days < thresholds.idle_days:
        return "slowing"
    if idle_days < thresholds.dormant_days:
        return "idle"
    return "dormant"


def current_status(auto_status: AutomaticStatus, mark: ManualStatus | None) -> CurrentStatus:
    return mark or auto_status


def calculate_kpi(
    projects: list[Project], online_users: list[OnlineUser], active_users_30d: int
) -> DashboardKpi:
    counts: dict[str, int] = {
        "active": 0,
        "slowing": 0,
        "idle": 0,
        "dormant": 0,
        "running": 0,
        "done": 0,
        "hold": 0,
    }
    for project in projects:
        counts[project.current_status] += 1
    return DashboardKpi(
        online_now=len(online_users),
        active_users_30d=active_users_30d,
        total_projects=len(projects),
        **counts,
    )


def idle_project_list(projects: list[Project]) -> list[IdleProject]:
    idle = [
        IdleProject(
            hashfname=project.hashfname,
            title=project.title,
            creator=project.creator,
            members=project.members,
            last_touch=project.last_touch,
            idle_days=project.idle_days,
        )
        for project in projects
        if project.current_status == "idle"
    ]
    return sorted(idle, key=lambda item: item.idle_days, reverse=True)
