"""
最低限の API 認証ミドルウェア。

設定の api_token（または環境変数 KAIRI_API_TOKEN）が空のときは開発モードとして許可。
設定されている場合は Authorization: Bearer <token> または X-API-Token を要求する。
"""
from __future__ import annotations

import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)

_PUBLIC_PREFIXES = (
    "/api/ping",
    "/ping",
    "/api/image/generate",  # <img src> は Authorization を送れない
    "/assets",
)

# 開発時のみ OpenAPI を公開パスに含める（KAIRI_RELEASE=1 では docs 自体が無い）
if os.environ.get("KAIRI_RELEASE", "").strip() not in ("1", "true", "TRUE", "yes"):
    _PUBLIC_PREFIXES = _PUBLIC_PREFIXES + (
        "/docs",
        "/openapi.json",
        "/redoc",
    )


def _configured_token() -> str:
    from app.routers.settings import app_settings
    settings = app_settings.get()
    token = (settings.get("api_token") or settings.get("app_pin") or "").strip()
    if not token:
        token = os.environ.get("KAIRI_API_TOKEN", "").strip()
    return token


class APITokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path or ""
        if request.method == "OPTIONS":
            return await call_next(request)
        if any(path == p or path.startswith(p + "/") for p in _PUBLIC_PREFIXES):
            return await call_next(request)
        # SPA 静的配信は認証対象外
        if not path.startswith("/api"):
            return await call_next(request)

        expected = _configured_token()
        if not expected:
            # 開発モード: トークン未設定なら許可（警告は起動時に一度）
            return await call_next(request)

        auth = request.headers.get("authorization") or ""
        header_token = request.headers.get("x-api-token") or ""
        bearer = ""
        if auth.lower().startswith("bearer "):
            bearer = auth[7:].strip()
        provided = bearer or header_token
        if provided != expected:
            logger.warning(f"Unauthorized API access: {request.method} {path}")
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)
