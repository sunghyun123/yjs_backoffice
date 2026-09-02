from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials

from app.domain import (
    GoogleCalendarEvent,
    GoogleDriveFile,
    GoogleWorkspaceSnapshot,
)


GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
)
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_EVENTS_URI = (
    "https://www.googleapis.com/calendar/v3/calendars/primary/events"
)
GOOGLE_DRIVE_FILES_URI = "https://www.googleapis.com/drive/v3/files"
GOOGLE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"

JsonGetter = Callable[[str, str], dict[str, Any]]
TokenProvider = Callable[[], str]


class GoogleWorkspaceCollector:
    """Reads only the CEO's Calendar events and configured Drive metadata."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        timezone: ZoneInfo,
        refresh_interval_sec: int,
        configured: bool,
        shared_drive_id: str = "",
        json_getter: JsonGetter | None = None,
        token_provider: TokenProvider | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._timezone = timezone
        self._refresh_interval_sec = refresh_interval_sec
        self._configured = configured
        self._shared_drive_id = shared_drive_id.strip()
        self._json_getter = json_getter or _get_json
        self._token_provider = token_provider

    @property
    def configured(self) -> bool:
        return self._configured

    @property
    def authorized(self) -> bool:
        return self._configured and bool(self._refresh_token)

    @property
    def drive_scope(self) -> str:
        return "shared" if self._shared_drive_id else "personal"

    def set_refresh_token(self, refresh_token: str) -> None:
        self._refresh_token = refresh_token

    def collect(self) -> GoogleWorkspaceSnapshot:
        now = datetime.now(self._timezone)
        week_start = now.date() - timedelta(days=now.weekday())
        week_end = week_start + timedelta(days=6)
        if not self._configured:
            return self._empty_snapshot(week_start, week_end)
        if not self.authorized:
            return self._empty_snapshot(week_start, week_end, configured=True)

        token = self._token_provider() if self._token_provider else self._access_token()
        events = self._fetch_events(token, week_start, week_end, now.date())
        files = self._fetch_files(token)
        return GoogleWorkspaceSnapshot(
            configured=True,
            authorized=True,
            drive_scope=self.drive_scope,
            refresh_interval_sec=self._refresh_interval_sec,
            fetched_at=now,
            week_start=week_start,
            week_end=week_end,
            events=events,
            files=files,
        )

    def _empty_snapshot(
        self,
        week_start: date,
        week_end: date,
        *,
        configured: bool = False,
    ) -> GoogleWorkspaceSnapshot:
        return GoogleWorkspaceSnapshot(
            configured=configured,
            authorized=False,
            drive_scope=self.drive_scope,
            refresh_interval_sec=self._refresh_interval_sec,
            week_start=week_start,
            week_end=week_end,
        )

    def _access_token(self) -> str:
        credentials = Credentials(
            token=None,
            refresh_token=self._refresh_token,
            token_uri=GOOGLE_TOKEN_URI,
            client_id=self._client_id,
            client_secret=self._client_secret,
            scopes=list(GOOGLE_SCOPES),
        )
        credentials.refresh(GoogleAuthRequest())
        if not credentials.token:
            raise RuntimeError("Google access token refresh returned no token")
        return credentials.token

    def _fetch_events(
        self,
        token: str,
        week_start: date,
        week_end: date,
        today: date,
    ) -> list[GoogleCalendarEvent]:
        start = datetime.combine(week_start, time.min, self._timezone)
        end = datetime.combine(week_end + timedelta(days=1), time.min, self._timezone)
        query = urlencode(
            {
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": "50",
                "timeZone": str(self._timezone),
                "fields": "items(id,summary,start,end,status)",
            }
        )
        payload = self._json_getter(f"{GOOGLE_CALENDAR_EVENTS_URI}?{query}", token)
        events: list[GoogleCalendarEvent] = []
        for item in payload.get("items", []):
            if item.get("status") == "cancelled":
                continue
            parsed = self._event_from_item(item, today)
            if parsed is not None:
                events.append(parsed)
        return events

    def _event_from_item(
        self,
        item: dict[str, Any],
        today: date,
    ) -> GoogleCalendarEvent | None:
        start_value = item.get("start") or {}
        end_value = item.get("end") or {}
        event_id = str(item.get("id") or "").strip()
        if not event_id:
            return None
        title = str(item.get("summary") or "제목 없는 일정").strip() or "제목 없는 일정"
        if start_value.get("date"):
            start_date = date.fromisoformat(str(start_value["date"]))
            end_date = (
                date.fromisoformat(str(end_value["date"]))
                if end_value.get("date")
                else start_date + timedelta(days=1)
            )
            return GoogleCalendarEvent(
                id=event_id,
                title=title,
                start_date=start_date,
                end_date=end_date,
                all_day=True,
                dday=(start_date - today).days,
            )
        if not start_value.get("dateTime"):
            return None
        starts_at = _parse_datetime(str(start_value["dateTime"]), self._timezone)
        ends_at = (
            _parse_datetime(str(end_value["dateTime"]), self._timezone)
            if end_value.get("dateTime")
            else None
        )
        return GoogleCalendarEvent(
            id=event_id,
            title=title,
            starts_at=starts_at,
            ends_at=ends_at,
            dday=(starts_at.date() - today).days,
        )

    def _fetch_files(self, token: str) -> list[GoogleDriveFile]:
        query_params = {
            "q": f"trashed = false and mimeType != '{GOOGLE_FOLDER_MIME_TYPE}'",
            "corpora": "drive" if self._shared_drive_id else "user",
            "spaces": "drive",
            "orderBy": "modifiedTime desc",
            "pageSize": "8",
            "fields": "files(id,name,mimeType,modifiedTime)",
        }
        if self._shared_drive_id:
            query_params.update(
                {
                    "driveId": self._shared_drive_id,
                    "includeItemsFromAllDrives": "true",
                    "supportsAllDrives": "true",
                }
            )
        query = urlencode(query_params)
        payload = self._json_getter(f"{GOOGLE_DRIVE_FILES_URI}?{query}", token)
        files: list[GoogleDriveFile] = []
        for item in payload.get("files", []):
            file_id = str(item.get("id") or "").strip()
            modified_time = str(item.get("modifiedTime") or "").strip()
            if not file_id or not modified_time:
                continue
            mime_type = str(item.get("mimeType") or "application/octet-stream")
            files.append(
                GoogleDriveFile(
                    id=file_id,
                    name=(
                        str(item.get("name") or "이름 없는 파일").strip()
                        or "이름 없는 파일"
                    ),
                    mime_type=mime_type,
                    kind=_file_kind(mime_type),
                    modified_at=_parse_datetime(modified_time, self._timezone),
                    open_url=f"https://drive.google.com/open?id={quote(file_id, safe='')}",
                )
            )
        return files


class DemoGoogleWorkspaceCollector:
    configured = True
    authorized = True
    drive_scope = "shared"

    def __init__(self, timezone: ZoneInfo, refresh_interval_sec: int) -> None:
        self._timezone = timezone
        self._refresh_interval_sec = refresh_interval_sec

    def set_refresh_token(self, refresh_token: str) -> None:
        return None

    def collect(self) -> GoogleWorkspaceSnapshot:
        now = datetime.now(self._timezone).replace(second=0, microsecond=0)
        week_start = now.date() - timedelta(days=now.weekday())
        events = [
            GoogleCalendarEvent(
                id="demo-event-1",
                title="주간 경영회의",
                starts_at=now + timedelta(days=1),
                ends_at=now + timedelta(days=1, hours=1),
                dday=1,
            ),
            GoogleCalendarEvent(
                id="demo-event-2",
                title="현장 방문",
                start_date=week_start + timedelta(days=4),
                end_date=week_start + timedelta(days=5),
                all_day=True,
                dday=((week_start + timedelta(days=4)) - now.date()).days,
            ),
        ]
        files = [
            GoogleDriveFile(
                id="demo-file-1",
                name="주간 경영 현황.xlsx",
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                kind="spreadsheet",
                modified_at=now - timedelta(minutes=8),
                open_url="https://drive.google.com/open?id=demo-file-1",
            ),
            GoogleDriveFile(
                id="demo-file-2",
                name="현장 점검 보고서.pdf",
                mime_type="application/pdf",
                kind="pdf",
                modified_at=now - timedelta(hours=2),
                open_url="https://drive.google.com/open?id=demo-file-2",
            ),
        ]
        return GoogleWorkspaceSnapshot(
            configured=True,
            authorized=True,
            drive_scope=self.drive_scope,
            refresh_interval_sec=self._refresh_interval_sec,
            fetched_at=now,
            week_start=week_start,
            week_end=week_start + timedelta(days=6),
            events=events,
            files=files,
        )


def _get_json(url: str, token: str) -> dict[str, Any]:
    request = UrlRequest(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urlopen(request, timeout=15) as response:  # noqa: S310 - fixed Google HTTPS URLs
        return json.loads(response.read().decode("utf-8"))


def _parse_datetime(value: str, timezone: ZoneInfo) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def _file_kind(mime_type: str) -> str:
    if mime_type.startswith("image/"):
        return "image"
    if "spreadsheet" in mime_type or "excel" in mime_type:
        return "spreadsheet"
    if mime_type == "application/pdf":
        return "pdf"
    if "presentation" in mime_type or "powerpoint" in mime_type:
        return "presentation"
    if mime_type.startswith("text/") or "document" in mime_type or "word" in mime_type:
        return "document"
    return "other"
