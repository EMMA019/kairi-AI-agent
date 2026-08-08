"""
Tools Router — ツール一覧・キャッシュ状態 API
フロントエンドからToolPanel/CacheMonitorで表示するためのエンドポイント
"""
from fastapi import APIRouter
from app.core.tools.registry import tool_registry
from app.core.cache_manager import CACHE_DB_PATH
import time
import json
import aiosqlite

router = APIRouter()


@router.get("/tools")
async def list_tools():
    """登録済みツール一覧を返す"""
    tools = []
    for name in tool_registry.list_tools():
        schema = tool_registry.get_schema(name)
        tools.append({
            "name": name,
            "schema": schema,
        })
    return {"tools": tools, "count": len(tools)}


@router.get("/cache/status")
async def cache_status():
    """キャッシュDBの状態を返す"""
    status = {}
    try:
        async with aiosqlite.connect(str(CACHE_DB_PATH)) as db:
            for table in ["llm_cache", "search_cache", "command_cache"]:
                cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")
                count = (await cursor.fetchone())[0]
                cursor = await db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE created_at > ?",
                    (time.time() - 1800,)
                )
                recent = (await cursor.fetchone())[0]
                status[table] = {"total": count, "recent_30min": recent}
    except Exception as e:
        return {"error": str(e)}
    return {"status": status}


@router.post("/tools/execute")
async def execute_tool(data: dict):
    """ツールを実行（フロントエンドからの手動実行）"""
    name = data.get("name", "")
    params = data.get("params", {})
    result = tool_registry.execute(name, params)
    return {"result": result}


# ============================================================
# MCPサーバー管理API（CLINE形式）
# ============================================================

@router.get("/mcp/servers/{server_name}/tools")
async def list_mcp_server_tools(server_name: str):
    """MCPサーバーの利用可能ツール一覧"""
    from app.core.mcp import mcp_manager
    tools = await mcp_manager.list_server_tools(server_name)
    return {"tools": tools, "server": server_name}


@router.get("/mcp/servers")
async def list_mcp_servers():
    """MCPサーバー一覧"""
    from app.core.mcp import mcp_manager
    return {"servers": mcp_manager.list_servers()}


@router.post("/mcp/servers")
async def add_mcp_server(data: dict):
    """MCPサーバーを追加（CLINE形式: npxコマンド等）"""
    from app.core.mcp import mcp_manager
    name = data.get("name", "")
    config = {
        "command": data.get("command", "npx"),
        "args": data.get("args", []),
        "env": data.get("env", {}),
        "description": data.get("description", ""),
        "type": data.get("type", "stdio"),
    }
    if mcp_manager.add_server(name, config):
        return {"success": True, "message": f"MCPサーバー '{name}' を追加しました"}
    return {"success": False, "message": "追加に失敗しました"}, 500


@router.delete("/mcp/servers/{server_name}")
async def remove_mcp_server(server_name: str):
    """MCPサーバーを削除"""
    from app.core.mcp import mcp_manager
    if mcp_manager.remove_server(server_name):
        return {"success": True, "message": f"MCPサーバー '{server_name}' を削除しました"}
    return {"success": False, "message": "削除に失敗しました"}, 500


@router.post("/mcp/servers/{server_name}/call")
async def call_mcp_tool(server_name: str, data: dict):
    """MCPサーバーのツールを呼び出す"""
    from app.core.mcp import mcp_manager
    tool_name = data.get("tool", "")
    arguments = data.get("arguments", {})
    result = await mcp_manager.call_tool(server_name, tool_name, arguments)
    return {"result": result}
