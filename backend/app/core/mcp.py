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
            self._start_reader()
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

    def _send(self, method: str, params: dict = None, timeout: float = 120.0) -> dict:
        if not self.start():
            return {"error": {"message": "起動失敗"}}
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

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        r = self._send("tools/call", {"name": tool_name, "arguments": arguments} if arguments else {"name": tool_name})
        if "error" in r: return f"[MCP Error] {r['error']}"
        content = r.get("result", {}).get("content", [])
        return "\n".join(c.get("text", str(c)) for c in content) if content else str(r.get("result", ""))

    def stop(self):
        self._running = False
        if self.process and self.process.poll() is None:
            try: self.process.terminate(); self.process.wait(timeout=5)
            except: self.process.kill()


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

    def stop_all(self):
        for p in self.processes.values(): p.stop()
        self.processes.clear()

mcp_manager = MCPManager()