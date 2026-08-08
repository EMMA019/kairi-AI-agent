"""BYOK key smoke-test (DeepSeek first). Used by first-run wizard."""
from __future__ import annotations

import os
from typing import Any

import httpx
import openai

from app.utils.logger import get_logger

logger = get_logger(__name__)


def _classify_openai_error(exc: BaseException) -> str:
    msg = str(exc).lower()
    status = getattr(exc, "status_code", None)
    if status is None and hasattr(exc, "response") and exc.response is not None:
        status = getattr(exc.response, "status_code", None)

    if isinstance(exc, openai.AuthenticationError) or status == 401:
        return "invalid_key"
    if status == 402 or any(
        x in msg for x in ("insufficient", "balance", "quota", "billing", "payment", "クレジット", "残高")
    ):
        return "balance"
    if isinstance(exc, openai.RateLimitError) or status == 429:
        return "rate_limit"
    if isinstance(exc, (openai.APIConnectionError, httpx.TimeoutException, httpx.ConnectError)):
        return "network"
    if "timeout" in msg or "connection" in msg or "network" in msg:
        return "network"
    return "unknown"


async def ping_deepseek_key(api_key: str) -> dict[str, Any]:
    """Hit DeepSeek with a minimal authenticated call. Does not persist the key."""
    key = (api_key or "").strip().strip("\"'")
    if not key:
        return {"ok": False, "error": "empty", "detail": "API key is empty"}

    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url.rstrip('/')}/v1"

    client = openai.AsyncOpenAI(
        api_key=key,
        base_url=base_url,
        timeout=httpx.Timeout(20.0, connect=10.0),
    )
    try:
        # models.list is enough to validate auth without spending completion tokens
        await client.models.list()
        return {"ok": True, "provider": "deepseek"}
    except Exception as e:
        code = _classify_openai_error(e)
        logger.warning(f"DeepSeek key ping failed: {code} ({e})")
        return {"ok": False, "error": code, "detail": str(e)[:300], "provider": "deepseek"}
    finally:
        try:
            await client.close()
        except Exception:
            pass
