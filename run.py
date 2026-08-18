from __future__ import annotations

import uvicorn

from app.config import get_settings


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "app.main:create_app",
        host=settings.app_host,
        port=settings.app_port,
        factory=True,
        workers=1,
        reload=False,
        access_log=False,
        server_header=False,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )
