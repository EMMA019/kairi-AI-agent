"""
Tool Registry — MCP的動的ツール登録機構

【CLINE対抗機能】
- CLINEのMCPサーバーに相当する動的ツール登録
- XMLの <mcp_call> タグから任意のツールを呼び出し可能
- プラグイン的に機能追加可能

【使い方】
1. ツール定義:
   @tool_registry.register(name="get_weather", description="天気を取得")
   def get_weather(city: str) -> str:
       return f"{city}の天気は晴れです"

2. Executorが呼び出し:
   <mcp_call tool="get_weather" city="Tokyo" />
"""
import json
import importlib
import inspect
from typing import Any, Callable, Optional
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ToolDef:
    """ツール定義"""
    def __init__(self, name: str, handler: Callable, description: str = "", schema: dict = None):
        self.name = name
        self.handler = handler
        self.description = description
        self.schema = schema or self._infer_schema(handler)
    
    def _infer_schema(self, handler: Callable) -> dict:
        """関数シグネチャからJSONスキーマを自動生成"""
        sig = inspect.signature(handler)
        properties = {}
        required = []
        for p_name, p_param in sig.parameters.items():
            if p_name == "self":
                continue
            p_type = str if p_param.annotation is inspect.Parameter.empty else p_param.annotation
            p_type_name = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}.get(p_type, "string")
            properties[p_name] = {"type": p_type_name, "description": f"Parameter {p_name}"}
            if p_param.default is inspect.Parameter.empty:
                required.append(p_name)
        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }
    
    def execute(self, params: dict) -> str:
        """ツールを実行"""
        try:
            result = self.handler(**params)
            return str(result)
        except Exception as e:
            logger.error(f"Tool execution error ({self.name}): {e}")
            return f"[ERROR] ツール実行エラー ({self.name}): {e}"


class ToolRegistry:
    """
    ツールレジストリ — MCP的動的ツール登録・実行
    
    シングルトンパターンで、アプリ全体で1つのインスタンスを共有。
    """
    
    def __init__(self):
        self._tools: dict[str, ToolDef] = {}
    
    def register(self, name: str = None, description: str = "", schema: dict = None):
        """
        デコレータとしてツールを登録。
        
        @tool_registry.register(name="my_tool", description="My tool")
        def my_tool(param1: str) -> str:
            ...
        """
        def decorator(func: Callable):
            tool_name = name or func.__name__
            tool_def = ToolDef(
                name=tool_name,
                handler=func,
                description=description,
                schema=schema,
            )
            self._tools[tool_name] = tool_def
            logger.info(f"🔧 Tool登録: {tool_name} - {description}")
            return func
        return decorator
    
    def register_module(self, module_path: str):
        """外部モジュールからツールを一括登録（MCP的プラグイン読み込み）"""
        try:
            module = importlib.import_module(module_path)
            for attr_name in dir(module):
                if attr_name.startswith("tool_"):
                    func = getattr(module, attr_name)
                    if callable(func):
                        self._tools[attr_name[5:]] = ToolDef(
                            name=attr_name[5:],
                            handler=func,
                            description=func.__doc__ or "",
                        )
                        logger.info(f"🔌 プラグイン読み込み: {module_path}.{attr_name}")
        except Exception as e:
            logger.error(f"プラグイン読み込みエラー ({module_path}): {e}")
    
    def get_tool(self, name: str) -> Optional[ToolDef]:
        return self._tools.get(name)
    
    def execute(self, name: str, params: dict) -> str:
        tool = self._tools.get(name)
        if not tool:
            return f"[ERROR] 不明なツール: {name}。利用可能: {', '.join(self.list_tools())}"
        return tool.execute(params)
    
    def list_tools(self) -> list[str]:
        return list(self._tools.keys())
    
    def get_schema(self, name: str) -> Optional[dict]:
        tool = self._tools.get(name)
        return tool.schema if tool else None
    
    def get_all_schemas(self) -> dict[str, dict]:
        return {name: tool.schema for name, tool in self._tools.items()}


# シングルトンインスタンス
tool_registry = ToolRegistry()


# ============================================================
# サンプルツール（ビルトイン）
# ============================================================

@tool_registry.register(name="echo", description="入力内容をそのまま返す（テスト用）")
def _echo(message: str) -> str:
    """エコーツール"""
    return f"Echo: {message}"


@tool_registry.register(name="list_tools", description="利用可能なツール一覧を表示")
def _list_tools() -> str:
    """ツール一覧表示（ローカル組み込み + 外部MCPサーバー）"""
    tools = tool_registry.list_tools()
    lines = [f"ローカルツール ({len(tools)}件):"]
    lines += [f"- {t}" for t in tools]
    # 外部MCPサーバー（Roblox_Studio 等）はローカル一覧には載らないため明示的に併記する。
    # 「この一覧に無い = 使えない」ではないことにモデルが気づけるようにする。
    try:
        from app.core.mcp import mcp_manager, MCPServerProcess
        for name, cfg in mcp_manager.servers.items():
            desc = (cfg.get("description") or "")[:80]
            lines.append(f"\n外部MCPサーバー「{name}」: {desc}")
            try:
                proc = mcp_manager.processes.get(name)
                if proc is None:
                    proc = MCPServerProcess(name, cfg)
                    mcp_manager.processes[name] = proc
                mcp_tools = proc.list_tools()
                if mcp_tools:
                    names = ", ".join(str(t.get("name", "?")) for t in mcp_tools if isinstance(t, dict))
                    lines.append(f"  ツール ({len(mcp_tools)}件): {names}")
                else:
                    lines.append("  (ツール一覧を取得できませんでした — サーバー未応答)")
                lines.append(f"  呼び出し方: <mcp_call server=\"{name}\" tool=\"ツール名\" args='{{\"key\": \"value\"}}' />")
            except Exception as e:
                lines.append(f"  (起動/取得失敗: {e})")
    except Exception:
        pass
    return "\n".join(lines)


@tool_registry.register(name="calc", description="簡単な計算を行う（式を文字列で渡す）")
def _calc(expression: str) -> str:
    """計算ツール（安全な式のみ実行）"""
    allowed = set("0123456789+-*/.() ")
    if not all(c in allowed for c in expression):
        return "[ERROR] 許可されていない文字が含まれています"
    try:
        result = eval(expression, {"__builtins__": {}}, {})
        return f"{expression} = {result}"
    except Exception as e:
        return f"[ERROR] 計算エラー: {e}"


@tool_registry.register(name="check_radar_logs", description="市場監視レーダーの直近の棄却ニュース一覧またはアラート通知履歴をDBから確認する。ログタイプ('rejected' または 'alert')と取得件数を指定可能。")
def _check_radar_logs(log_type: str = "rejected", limit: int = 10) -> str:
    """監視レーダーのログ(棄却・通知)確認ツール"""
    import sqlite3
    from app.core.monitor.watchlist import DB_PATH
    import os
    if not os.path.exists(DB_PATH):
        return "[INFO] 監視データベース (monitor.db) がまだ作成されていないか、データがありません。"
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        if log_type == "alert":
            cursor.execute("SELECT title, importance, catalyst_type, notified_at FROM alert_history ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            if not rows:
                return "【通知済みアラート履歴】: まだ通知されたニュースはありません。"
            res = [f"🚨 【通知済み一覧 (直近{len(rows)}件)】"]
            for r in rows:
                res.append(f"- [{r[1]}pt] {r[0]} (カタリスト: {r[2]} / 時間: {r[3]})")
            return "\n".join(res)
        else:
            cursor.execute("SELECT title, raw_score, reason, created_at FROM rejected_news_log ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            if not rows:
                return "【棄却ニュース履歴】: まだカットされたニュースログはありません。"
            res = [f"📉 【カット(棄却)されたニュース一覧 (直近{len(rows)}件)】"]
            for r in rows:
                res.append(f"- [{r[1]}pt] 「{r[0]}」 (理由: {r[2]} / 時間: {r[3]})")
            return "\n".join(res)
    except Exception as e:
        return f"[ERROR] ログ取得エラー: {e}"
    finally:
        try:
            conn.close()
        except Exception:
            pass


# 専門ツールモジュールの自動ロード
try:
    import app.core.tools.travel
except Exception as e:
    logger.warning(f"travelツールのロードに失敗しました: {e}")

try:
    import app.core.tools.quant_tools
except Exception as e:
    logger.warning(f"quantツールのロードに失敗しました: {e}")

try:
    import app.core.tools.market_data
except Exception as e:
    logger.warning(f"market_dataツールのロードに失敗しました: {e}")

try:
    import app.core.tools.ibkr_tools
except Exception as e:
    logger.warning(f"ibkrツールのロードに失敗しました: {e}")