from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.responses import JSONResponse, Response

from app.config import Settings


Handler = Callable[[Request], Awaitable[Response]]


def install_security_middleware(app: object, settings: Settings) -> None:
    @app.middleware("http")  # type: ignore[attr-defined]
    async def security_headers(request: Request, call_next: Handler) -> Response:
        if settings.app_trust_tailscale_headers:
            login = request.headers.get("Tailscale-User-Login", "").strip().lower()
            allowed = settings.app_allowed_tailscale_user.strip().lower()
            if not login or login != allowed:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "허용되지 않은 사용자입니다."},
                    headers={"Cache-Control": "no-store"},
                )

        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("Origin")
            if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "동일 출처 요청만 허용됩니다."},
                    headers={"Cache-Control": "no-store"},
                )

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
        return response
