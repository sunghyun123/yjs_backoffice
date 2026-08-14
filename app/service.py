from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.config import Settings
from app.domain import (
    DashboardSnapshot,
    MailItem,
    MailSnapshot,
    OnlineUser,
    Project,
    RecentEdit,
    StatusThresholds,
    calculate_kpi,
    classify_project,
    current_status,
    idle_project_list,
)
from app.repository import DashboardRepository, Row, require_datetime


def kst_datetime(value: datetime, settings: Settings) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=settings.timezone)
    return value.astimezone(settings.timezone)


def safe_text(value: Any, fallback: str = "") -> str:
    return str(value).strip() if value is not None else fallback


class DashboardService:
    def __init__(
        self,
        repository: DashboardRepository,
        settings: Settings,
        thresholds: StatusThresholds | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._thresholds = thresholds or StatusThresholds()

    def load_core(self, *, recent_edits: list[RecentEdit] | None = None) -> DashboardSnapshot:
        now = datetime.now(self._settings.timezone)
        projects = [self._project_from_row(row) for row in self._repository.fetch_projects()]
        online_users = [
            self._online_user_from_row(row)
            for row in self._repository.fetch_online_users(self._thresholds.online_minutes)
        ]
        active_users_30d = self._repository.fetch_active_users_30d()
        return DashboardSnapshot(
            generated_at=now,
            kpi=calculate_kpi(projects, online_users, active_users_30d),
            idle_projects=idle_project_list(projects),
            projects=projects,
            recent_edits=recent_edits or [],
            online_users=online_users,
            mail=self._demo_mail(now)
            if self._settings.app_demo_mode
            else MailSnapshot(refresh_interval_sec=self._settings.mail_refresh_seconds),
        )

    def load_recent_edits(self, limit: int = 30) -> list[RecentEdit]:
        return [
            RecentEdit(
                at=kst_datetime(require_datetime(row, "c_date"), self._settings),
                who=safe_text(row.get("u_name"), "알 수 없음"),
                gubun=safe_text(row.get("gubun")),
                detail=safe_text(row.get("detail")),
                project=safe_text(row.get("project")) or None,
            )
            for row in self._repository.fetch_recent_edits(limit)
        ]

    def _project_from_row(self, row: Row) -> Project:
        idle_days = max(int(row.get("idle_days") or 0), 0)
        auto = classify_project(idle_days, self._thresholds)
        mark = None  # Phase 3에서 SQLite project_mark와 결합합니다.
        return Project(
            hashfname=safe_text(row.get("HASHFNAME")),
            title=safe_text(row.get("TITLE"), "제목 없음"),
            owner=safe_text(row.get("MEMBER_NAME")) or None,
            members=max(int(row.get("member_cnt") or 0), 0),
            tree_cnt=max(int(row.get("TREE_CNT") or 0), 0),
            last_touch=kst_datetime(require_datetime(row, "last_touch"), self._settings),
            idle_days=idle_days,
            auto_status=auto,
            mark=mark,
            current_status=current_status(auto, mark),
        )

    def _online_user_from_row(self, row: Row) -> OnlineUser:
        return OnlineUser(
            user_id=safe_text(row.get("u_id")),
            name=safe_text(row.get("MEMBER_NAME"), "알 수 없음"),
            project=safe_text(row.get("TITLE")) or None,
            at=kst_datetime(require_datetime(row, "uptime"), self._settings),
        )

    def _demo_mail(self, now: datetime) -> MailSnapshot:
        items = [
            MailItem(
                account="daou",
                sender="(주)한전기업 김상무",
                subject="8월 기성 청구서 송부의 건",
                at=now - timedelta(minutes=12),
                mailbox_url="#",
            ),
            MailItem(
                account="daou",
                sender="안양시청 전기과",
                subject="덕천지구 인허가 보완 요청",
                at=now - timedelta(minutes=46),
                mailbox_url="#",
            ),
            MailItem(
                account="gmail",
                sender="대한전선 영업팀",
                subject="케이블 단가 인상 안내",
                at=now - timedelta(minutes=79),
                mailbox_url="#",
            ),
            MailItem(
                account="naver",
                sender="한국전기공사협회",
                subject="하반기 교육 일정 안내",
                at=now - timedelta(minutes=114),
                mailbox_url="#",
            ),
        ]
        return MailSnapshot(
            refresh_interval_sec=self._settings.mail_refresh_seconds,
            fetched_at=now,
            unread_total=20,
            unread_by_account={"daou": 12, "gmail": 5, "naver": 3},
            items=items,
        )


class DemoRepository:
    """Deterministic in-process data for local UI and API development."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _now(self) -> datetime:
        return datetime.now(self._settings.timezone).replace(second=0, microsecond=0)

    def fetch_projects(self) -> list[Row]:
        now = self._now()
        samples = [
            ("demo-001", "삼성 평택 3기 전기공사", "박준호", 6, 418, 0),
            ("demo-002", "시흥 배곧 상가 전기 인입", "이현우", 4, 276, 0),
            ("demo-003", "2026 하반기 자재 단가 협상", "정다은", 3, 132, 1),
            ("demo-004", "광명 KTX 역사 조명 개선", "최민석", 5, 351, 1),
            ("demo-005", "인천 공장 전력 품질 진단", "임재혁", 2, 88, 10),
            ("demo-006", "안양 덕천지구 아파트 수변전 설비", "이현우", 4, 219, 26),
            ("demo-007", "부천 공장 동력설비 증설", "임재혁", 3, 145, 23),
            ("demo-008", "2026 상반기 안전관리 계획", "정다은", 8, 362, 21),
            ("demo-009", "김포 물류센터 조명·전열 설계", "최민석", 3, 190, 17),
            ("demo-010", "하남 오피스텔 소방전기 감리", "강태윤", 3, 154, 15),
            ("demo-011", "2024 공장동 수전설비 보수", "한지우", 4, 214, 640),
        ]
        return [
            {
                "HASHFNAME": hashfname,
                "TITLE": title,
                "MEMBER_NAME": owner,
                "member_cnt": members,
                "TREE_CNT": tree_cnt,
                "last_touch": now - timedelta(days=idle_days),
                "idle_days": idle_days,
            }
            for hashfname, title, owner, members, tree_cnt, idle_days in samples
        ]

    def fetch_online_users(self, online_minutes: int) -> list[Row]:
        now = self._now()
        return [
            {"u_id": "u001", "MEMBER_NAME": "박준호", "uptime": now, "TITLE": "삼성 평택 3기 전기공사"},
            {"u_id": "u002", "MEMBER_NAME": "이현우", "uptime": now - timedelta(minutes=4), "TITLE": "시흥 배곧 상가 전기 인입"},
            {"u_id": "u003", "MEMBER_NAME": "정다은", "uptime": now - timedelta(minutes=5), "TITLE": "2026 하반기 자재 단가 협상"},
            {"u_id": "u004", "MEMBER_NAME": "최민석", "uptime": now - timedelta(minutes=7), "TITLE": "광명 KTX 역사 조명 개선"},
        ]

    def fetch_active_users_30d(self) -> int:
        return 7

    def fetch_recent_edits(self, limit: int = 30) -> list[Row]:
        now = self._now()
        samples = [
            (0, "박준호", "ADD", "3층 분전반 결선 완료", "삼성 평택 3기 전기공사"),
            (4, "이현우", "EDIT", "케이블 트레이 규격 변경 검토", "시흥 배곧 상가 전기 인입"),
            (5, "정다은", "LINK", "8월_기성내역서.xlsx", "2026 하반기 자재 단가 협상"),
            (7, "최민석", "MOVE", "조명 배치도 검토", "광명 KTX 역사 조명 개선"),
        ]
        return [
            {
                "c_date": now - timedelta(minutes=minutes),
                "u_name": who,
                "gubun": gubun,
                "detail": detail,
                "project": project,
            }
            for minutes, who, gubun, detail, project in samples[:limit]
        ]

    def close(self) -> None:
        return None
