"""Unit tests for DeepSeek key ping error classification (no network)."""
from app.core.key_ping import _classify_openai_error


def test_classify_invalid_key_status():
    exc = Exception("auth failed")
    exc.status_code = 401  # type: ignore[attr-defined]
    assert _classify_openai_error(exc) == "invalid_key"


def test_classify_balance_message():
    assert _classify_openai_error(Exception("Insufficient Balance")) == "balance"


def test_classify_rate_limit_status():
    exc = Exception("too many")
    exc.status_code = 429  # type: ignore[attr-defined]
    assert _classify_openai_error(exc) == "rate_limit"


def test_classify_network_message():
    assert _classify_openai_error(Exception("Connection timeout to host")) == "network"


def test_classify_unknown():
    assert _classify_openai_error(Exception("weird boom")) == "unknown"
