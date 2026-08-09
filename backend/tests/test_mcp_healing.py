"""MCP自己修復・パーサー強化の単体テスト。

対象:
- app.core.tools.handler._parse_mcp_args （args属性のJSONパース＋エスケープ許容）
- app.core.mcp.MCPServerProcess._ensure_datamodel_type 系の判定ヘルパー（_is_roblox）
- app.core.auto_execution_loop.loop._error_signature （同一エラー重複検出用シグネチャ）
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.tools.handler import _parse_mcp_args
from app.core.mcp import MCPServerProcess
from app.core.auto_execution_loop.loop import _error_signature


# --- _parse_mcp_args ---

def test_parse_mcp_args_plain_json():
    assert _parse_mcp_args('{"datamodel_type": "Edit", "max_depth": 2}') == {
        "datamodel_type": "Edit",
        "max_depth": 2,
    }


def test_parse_mcp_args_empty():
    assert _parse_mcp_args("") == {}
    assert _parse_mcp_args("   ") == {}
    assert _parse_mcp_args(None) == {}


def test_parse_mcp_args_escaped_quotes():
    # args="{\"datamodel_type\": \"Edit\"}" のようなリテラルバックスラッシュ形式
    assert _parse_mcp_args('{\\"datamodel_type\\": \\"Edit\\"}') == {"datamodel_type": "Edit"}


def test_parse_mcp_args_invalid_falls_back_to_raw():
    assert _parse_mcp_args("not json at all") == {"raw_input": "not json at all"}


def test_parse_mcp_args_non_dict_json_wrapped():
    # dict以外のJSONは raw_input にラップ（MCPのargumentsはdictである必要があるため）
    assert _parse_mcp_args("[1, 2, 3]") == {"raw_input": "[1, 2, 3]"}


# --- MCPServerProcess._is_roblox ---

def test_is_roblox_detection():
    assert MCPServerProcess._is_roblox(SimpleNamespace(name="Roblox_Studio")) is True
    assert MCPServerProcess._is_roblox(SimpleNamespace(name="roblox-dev")) is True
    assert MCPServerProcess._is_roblox(SimpleNamespace(name="filesystem")) is False
    assert MCPServerProcess._is_roblox(SimpleNamespace(name="")) is False


# --- _error_signature ---

def test_error_signature_normalizes_whitespace():
    assert _error_signature("datamodel_type\n is   required") == "datamodel_type is required"


def test_error_signature_truncates_to_150():
    sig = _error_signature("abcdefghij " * 50)
    assert len(sig) <= 150


def test_error_signature_none_safe():
    assert _error_signature(None) == ""
    assert _error_signature("") == ""


# --- ローカルmcp_call（Server->Tool連結形式）のargsアンラップ挙動 ---

def test_local_mcp_call_args_unwrap_via_handler():
    """tool="Server->Tool" args='{...}' 形式で datamodel_type がトップレベルに展開されること。"""
    import asyncio
    from app.core.tools.handler import ToolHandler

    handler = ToolHandler(session_id="test-session", mode="task")

    captured = {}

    class FakeManager:
        servers = {"Roblox_Studio": {}}

        async def call_tool(self, server_name, tool_name, arguments):
            captured["server"] = server_name
            captured["tool"] = tool_name
            captured["arguments"] = arguments
            return "OK"

    import app.core.mcp as mcp_module

    original = getattr(mcp_module, "mcp_manager", None)
    mcp_module.mcp_manager = FakeManager()
    try:
        response = (
            '<mcp_call tool="Roblox_Studio->search_game_tree" '
            'args=\'{"datamodel_type": "Edit", "max_depth": 2}\' />'
        )
        asyncio.run(handler._handle_mcp_tools(response))
    finally:
        if original is not None:
            mcp_module.mcp_manager = original

    assert captured.get("server") == "Roblox_Studio"
    assert captured.get("tool") == "search_game_tree"
    # 重要: datamodel_type が文字列内に埋もれずトップレベル引数として渡ること
    assert captured.get("arguments", {}).get("datamodel_type") == "Edit"
    assert captured.get("arguments", {}).get("max_depth") == "2" or captured.get("arguments", {}).get("max_depth") == 2