from __future__ import annotations

from collections.abc import Awaitable, Callable
from urllib.parse import SplitResult, urlsplit

from fastapi import Request
from starlette.responses import JSONResponse, Response

from app.config import Settings


Handler = Callable[[Request], Awaitable[Response]]


def _parse_origin(value: str) -> SplitResult | None:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    return parsed


def _authority_matches(origin: SplitResult, authority: str) -> bool:
    candidate = authority.split(",", 1)[0].strip()
    try:
        parsed = urlsplit(f"//{candidate}")
        candidate_port = parsed.port
    except ValueError:
        return False
    if not parsed.hostname or parsed.hostname.lower() != origin.hostname.lower():
        return False
    origin_port = origin.port or (443 if origin.scheme == "https" else 80)
    return candidate_port is None or candidate_port == origin_port


def is_same_origin(request: Request, origin_value: str, *, trust_tls_proxy: bool) -> bool:
    origin = _parse_origin(origin_value)
    if origin is None:
        return False
    forwarded_host = request.headers.get("X-Forwarded-Host", "")
    host = request.headers.get("Host", "")
    if not any(
        authority and _authority_matches(origin, authority)
        for authority in (forwarded_host, host)
    ):
        return False
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
    request_scheme = forwarded_proto.split(",", 1)[0].strip() or request.url.scheme
    if origin.scheme == request_scheme:
        return True
    return trust_tls_proxy and request_scheme == "http" and origin.scheme == "https"


def install_security_middleware(app: object, settings: Settings) -> None:
    @app.middleware("http")  # type: ignore[attr-defined]
    async def security_headers(request: Request, call_next: Handler) -> Response:
        response: Response | None = None
        if settings.app_trust_tailscale_headers:
            login = request.headers.get("Tailscale-User-Login", "").strip().lower()
            allowed = settings.app_allowed_tailscale_user.strip().lower()
            if not login or login != allowed:
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "허용되지 않은 사용자입니다."},
                )

        if response is None and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("Origin")
            origin_required = settings.app_trust_tailscale_headers
            origin_mismatch = bool(origin) and not is_same_origin(
                request,
                origin,
                trust_tls_proxy=settings.app_trust_tailscale_headers,
            )
            if (origin_required and not origin) or origin_mismatch:
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "동일 출처 요청만 허용됩니다."},
                )

        if response is None:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if settings.app_trust_tailscale_headers:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response
