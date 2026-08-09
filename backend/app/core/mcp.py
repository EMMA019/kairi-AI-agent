"""
MCP (Model Context Protocol) クライアントマネージャー
CLINEのnpx MCPサーバーパターンを完全再現。
- stdio: npxコマンドを子プロセスとして実行、stdin/stdoutでJSON-RPC通信
"""
import json
import asyncio
import subprocess
import threading
import os
import re
import time
from pathlib import Path
from typing import Optional
from app.utils.logger import get_logger

logger = get_logger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config" / "mcp_servers.json"


class MCPServerProcess:
    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._responses: dict[int, str] = {}
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False
        self._initialized = False
        self._started_at: Optional[float] = None

    def start(self):
        if self._running and self.process and self.process.poll() is None:
            return True
        cmd = self.config.get("command", "npx")
        args = self.config.get("args", [])
        env = self.config.get("env", {})
        full_env = {**os.environ, **env} if env else None
        shell_cmd = f"{cmd} {' '.join(args)}"
        try:
            if os.name == 'nt':
                self.process = subprocess.Popen(
                    ['cmd.exe', '/c', shell_cmd], stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=full_env,
                )
            else:
                self.process = subprocess.Popen(
                    [cmd] + args, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=full_env,
                )
            self._running = True
            self._initialized = False  # 新プロセスはハンドシェイク未実施
            self._started_at = time.time()
            self._start_reader()
            self._start_stderr_drain()
            logger.info(f"✅ MCP起動: {self.name}")
            return True
        except Exception as e:
            logger.error(f"❌ MCP起動失敗: {self.name} - {e}")
            return False

    def _start_reader(self):
        """別スレッドでstdoutを行単位+JSON連結で読み続ける"""
        def _reader():
            buf = ""
            while self._running and self.process:
                try:
                    line = self.process.stdout.readline()
                    if not line:
                        break
                    text = line.decode('utf-8', errors='ignore').strip()
                    if not text:
                        continue
                    buf += text
                    # '}'で終わってたらJSONが閉じてると判断
                    if text.endswith('}'):
                        try:
                            data = json.loads(buf)
                            rid = data.get("id")
                            if rid is not None:
                                with self._lock:
                                    self._responses[rid] = buf
                            buf = ""
                        except json.JSONDecodeError:
                            pass  # まだ途中
                except Exception:
                    break
        self._reader_thread = threading.Thread(target=_reader, daemon=True)
        self._reader_thread.start()

    def _start_stderr_drain(self):
        """stderrを吸い上げる（パイプバッファ満杯による子プロセスのデッドロック防止＋ログ可視化）"""
        def _drain():
            while self._running and self.process:
                try:
                    line = self.process.stderr.readline()
                    if not line:
                        break
                    text = line.decode('utf-8', errors='ignore').strip()
                    if text:
                        logger.debug(f"[MCP:{self.name}:stderr] {text[:300]}")
                except Exception:
                    break
        t = threading.Thread(target=_drain, daemon=True)
        t.start()

    def _do_initialize(self) -> bool:
        """MCPプロトコルの initialize ハンドシェイク（プロセス起動後の初回のみ必須）"""
        if self._initialized:
            return True
        self._request_id += 1
        rid = self._request_id
        req = {
            "jsonrpc": "2.0", "id": rid, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "kairi", "version": "1.0"},
            },
        }
        try:
            import time
            self.process.stdin.write((json.dumps(req) + "\n").encode())
            self.process.stdin.flush()
            deadline = time.time() + 30
            while time.time() < deadline:
                with self._lock:
                    if rid in self._responses:
                        self._responses.pop(rid)
                        break
                time.sleep(0.1)
            else:
                logger.error(f"❌ MCP initialize タイムアウト: {self.name}")
                return False
            note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            self.process.stdin.write((json.dumps(note) + "\n").encode())
            self.process.stdin.flush()
            self._initialized = True
            logger.info(f"🤝 MCP initialize完了: {self.name}")
            return True
        except Exception as e:
            logger.error(f"❌ MCP initialize失敗: {self.name} - {e}")
            return False

    def _send(self, method: str, params: dict = None, timeout: float = 120.0) -> dict:
        if not self.start():
            return {"error": {"message": "起動失敗"}}
        if method != "initialize" and not self._do_initialize():
            return {"error": {"message": "initialize失敗"}}
        self._request_id += 1
        rid = self._request_id
        req = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params: req["params"] = params
        try:
            self.process.stdin.write((json.dumps(req) + "\n").encode())
            self.process.stdin.flush()
            import time
            deadline = time.time() + timeout
            while time.time() < deadline:
                with self._lock:
                    if rid in self._responses:
                        return json.loads(self._responses.pop(rid))
                time.sleep(0.1)
            return {"error": {"message": f"タイムアウト({timeout}秒)"}}
        except Exception as e:
            return {"error": {"message": str(e)}}

    def list_tools(self):
        r = self._send("tools/list")
        if "error" in r: return []
        return r.get("result", {}).get("tools", [])

    # 起動直後の一過性エラー（WSブリッジ接続待ち等）のマーカー
    _TRANSIENT_MARKERS = (
        "Not connected to the WS host",
        "Unable to find an active Studio instance",
        "active Studio instance is not yet set",
    )

    def _is_roblox(self) -> bool:
        return "roblox" in (self.name or "").lower()

    def _try_recover_active_studio(self) -> bool:
        """Roblox: アクティブStudio未設定時に list_roblox_studios → set_active_studio で最初のインスタンスを自動選択する。"""
        try:
            r = self._send("tools/call", {"name": "list_roblox_studios", "arguments": {}})
            if not isinstance(r, dict) or "error" in r:
                logger.warning(f"⚠️ Roblox復旧: list_roblox_studios 失敗: {str(r)[:200]}")
                return False
            result = r.get("result", {}) or {}
            content = result.get("content", [])
            text = "\n".join(c.get("text", str(c)) for c in content) if content else str(result)
            m = re.search(r'"id"\s*:\s*"([^"]+)"', text)
            if not m:
                logger.warning("⚠️ Roblox復旧: studio id を取得できませんでした（Roblox StudioがPlaceを開いた状態で起動中か確認）")
                return False
            studio_id = m.group(1)
            r2 = self._send("tools/call", {"name": "set_active_studio", "arguments": {"studio_id": studio_id}})
            if isinstance(r2, dict) and "error" in r2:
                logger.warning(f"⚠️ Roblox set_active_studio 失敗: {str(r2['error'])[:200]}")
                return False
            res2 = r2.get("result", {}) if isinstance(r2, dict) else {}
            if isinstance(res2, dict) and res2.get("isError"):
                c2 = res2.get("content", [])
                t2 = "\n".join(c.get("text", str(c)) for c in c2) if c2 else str(res2)
                logger.warning(f"⚠️ Roblox set_active_studio がエラーを返しました: {t2[:200]}")
                return False
            logger.info(f"✅ Roblox: アクティブStudioを自動設定しました ({studio_id})")
            return True
        except Exception as e:
            logger.warning(f"⚠️ Roblox アクティブStudio自動復旧中に例外: {e}")
            return False

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        arguments = dict(arguments or {})
        payload = {"name": tool_name, "arguments": arguments} if arguments else {"name": tool_name}
        logger.info(f"🔌 MCP呼び出し: {self.name}/{tool_name}")
        max_attempts = 4
        active_recovered = False
        datamodel_retried = False
        for attempt in range(1, max_attempts + 1):
            r = self._send("tools/call", payload)
            if "error" in r:
                logger.warning(f"[MCP Error] {self.name}/{tool_name}: {str(r['error'])[:300]}")
                return f"[MCP Error] {r['error']}"
            result = r.get("result", {})
            content = result.get("content", [])
            text = "\n".join(c.get("text", str(c)) for c in content) if content else str(result)
            # MCP仕様の isError を明示エラー表記に変換（下流のエラー検出を確実にするため）。
            # 例: Roblox Studio の "datamodel_type is required" は isError=true のプレーンテキストで返る。
            if isinstance(result, dict) and result.get("isError"):
                # (1) Roblox: datamodel_type欠落 → "Edit" を自動補完して1回だけリトライ
                if (self._is_roblox() and not datamodel_retried
                        and "datamodel_type is required" in text):
                    datamodel_retried = True
                    arguments = {**arguments, "datamodel_type": "Edit"}
                    payload = {"name": tool_name, "arguments": arguments}
                    logger.info(f"🔧 {self.name}/{tool_name}: datamodel_type='Edit' を自動補完してリトライします")
                    continue
                # (2) Roblox: アクティブStudio未設定 → 最初のインスタンスを自動選択して1回だけリトライ
                #     （起動直後でなくても復旧する。StudioMCPはPlaceを開いていてもactive未設定のことがある）
                if (self._is_roblox() and not active_recovered
                        and ("active Studio instance is not yet set" in text
                             or "Unable to find an active Studio instance" in text)):
                    active_recovered = True
                    logger.warning(f"⚠️ {self.name}: アクティブStudio未設定 → 自動選択を試みます")
                    if self._try_recover_active_studio():
                        continue
                # 起動直後の一過性エラーは自動リトライ（StudioMCP等のWSブリッジ接続待ち）
                age = time.time() - self._started_at if self._started_at else 999.0
                if (attempt < max_attempts and age < 30.0
                        and any(m in text for m in self._TRANSIENT_MARKERS)):
                    logger.info(f"🔁 MCP一過性エラーのためリトライ ({attempt}/{max_attempts}): {self.name}")
                    time.sleep(0.8)
                    continue
                # 引数エラーには有効値ヒントを付記し、LLM（executor/supervisor）が正しい値で自己修復できるようにする
                if "datamodel_type is required" in text or "Invalid datamodel_type" in text:
                    text += "\n(hint: datamodel_type の有効値は \"Edit\" / \"Client\" / \"Server\" の3つのみ。編集中のPlace操作は \"Edit\" を指定)"
                logger.warning(f"[MCP Tool Error] {self.name}/{tool_name}: {text[:300]}")
                return f"[MCP Tool Error] {text}"
            return text
        return "[MCP Tool Error] リトライ回数超過"

    def stop(self):
        self._running = False
        if self.process and self.process.poll() is None:
            try:
                if os.name == 'nt':
                    # cmd.exe 経由で起動しているため、terminate だけでは実際の
                    # MCPサーバー子プロセス（StudioMCP.exe 等）が孤児化する。
                    # taskkill /T でプロセスツリーごと停止する。
                    subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                                   capture_output=True, timeout=5)
                else:
                    self.process.terminate(); self.process.wait(timeout=5)
            except Exception:
                try: self.process.kill()
                except Exception: pass


class MCPManager:
    def __init__(self):
        self.servers: dict = {}
        self.processes: dict[str, MCPServerProcess] = {}
        self.load_config()

    def load_config(self):
        if not CONFIG_PATH.exists():
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps({"mcpServers": {
                "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", str(BASE_DIR).replace('\\', '/') + "/workspace"], "description": "ファイル操作用"},
            }}, indent=2), encoding="utf-8")
        try:
            self.servers = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("mcpServers", {})
            logger.info(f"📋 MCP: {len(self.servers)}件")
        except Exception as e:
            logger.error(f"MCP設定エラー: {e}")

    def save_config(self) -> bool:
        try:
            CONFIG_PATH.write_text(json.dumps({"mcpServers": self.servers}, indent=2), encoding="utf-8")
            return True
        except: return False

    def list_servers(self) -> list:
        return [{"name": n, "command": c.get("command",""), "args": c.get("args",[]), "description": c.get("description","")} for n,c in self.servers.items()]

    def add_server(self, name: str, config: dict) -> bool:
        self.servers[name] = {"command": config.get("command","npx"), "args": config.get("args",[]), "env": config.get("env",{}), "description": config.get("description",""), "type": "stdio"}
        return self.save_config()

    def remove_server(self, name: str) -> bool:
        if name in self.processes: self.processes[name].stop(); del self.processes[name]
        self.servers.pop(name, None)
        return self.save_config()

    async def list_server_tools(self, server_name: str) -> list:
        if server_name not in self.processes:
            cfg = self.servers.get(server_name)
            if not cfg: return [{"error": "サーバーなし"}]
            self.processes[server_name] = MCPServerProcess(server_name, cfg)
        return await asyncio.get_event_loop().run_in_executor(None, self.processes[server_name].list_tools)

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> str:
        if server_name not in self.processes:
            cfg = self.servers.get(server_name)
            if not cfg: return f"[ERROR] サーバーなし"
            self.processes[server_name] = MCPServerProcess(server_name, cfg)
        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: self.processes[server_name].call_tool(tool_name, arguments))

    def start_autostart_servers(self):
        """設定で autostart: true のサーバーをバックグラウンドで先行起動（initializeまで）"""
        for name, cfg in self.servers.items():
            if not cfg.get("autostart"):
                continue
            def _warm(n=name, c=cfg):
                try:
                    proc = self.processes.get(n)
                    if not proc:
                        proc = MCPServerProcess(n, c)
                        self.processes[n] = proc
                    proc.list_tools()  # start + initialize まで完了する
                    logger.info(f"🚀 MCP自動起動完了: {n}")
                except Exception as e:
                    logger.warning(f"MCP自動起動失敗: {n} - {e}")
            threading.Thread(target=_warm, daemon=True).start()

    def stop_all(self):
        for p in self.processes.values(): p.stop()
        self.processes.clear()

mcp_manager = MCPManager()