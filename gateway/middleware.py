"""Host restrictions for internal dashboard routes."""
import os

from fastapi import Request
from fastapi.responses import HTMLResponse


async def restrict_internal_routes(request: Request, call_next):
    public_prefixes = ["/assets/", "/favicon.svg", "/api/send-", "/api/status", "/api/check-", "/api/device/", "/api/groups", "/api/group-info", "/api/convert-jid", "/api/newsletter/", "/api/airich/", "/api/blast", "/docs", "/openapi.json", "/static"]
    if not any(request.url.path.startswith(prefix) for prefix in public_prefixes):
        host = request.headers.get("host", "")
        allowed = os.getenv("GATEWAY_ALLOWED_HOSTS", "utusan.chat,localhost:8880,127.0.0.1:8880,localhost:5173,127.0.0.1:5173,testserver").split(",")
        if host not in allowed:
            return HTMLResponse("Host tidak diizinkan", status_code=403)
    response = await call_next(request)
    return response
