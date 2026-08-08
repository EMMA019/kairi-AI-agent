"""Roblox Studio MCP 接続スモークテスト（Kairi の MCPManager と同じ stdio 手順を再現）"""
import json
import subprocess
import threading
import time
import sys

CMD = ["cmd.exe", "/c", "bin\\roblox_studio_mcp.bat"]


def read_stdout(proc, results, stop):
    buf = ""
    while not stop.is_set():
        line = proc.stdout.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="ignore").strip()
        if not text:
            continue
        buf += text
        if text.endswith("}"):
            try:
                data = json.loads(buf)
                if data.get("id") is not None:
                    results[data["id"]] = data
                buf = ""
            except json.JSONDecodeError:
                pass


def main():
    proc = subprocess.Popen(
        CMD, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    results = {}
    stop = threading.Event()
    t = threading.Thread(target=read_stdout, args=(proc, results, stop), daemon=True)
    t.start()

    def send(rid, method, params=None):
        req = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params:
            req["params"] = params
        proc.stdin.write((json.dumps(req) + "\n").encode("utf-8"))
        proc.stdin.flush()

    send(1, "initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "kairi-test", "version": "1.0"},
    })

    deadline = time.time() + 15
    while 1 not in results and time.time() < deadline:
        time.sleep(0.2)

    if 1 not in results:
        print("❌ initialize 応答なし（15秒タイムアウト）")
        stop.set()
        proc.kill()
        sys.exit(1)

    server_info = results[1].get("result", {}).get("serverInfo", {})
    print(f"✅ initialize OK: serverInfo={server_info}")

    # initialized 通知
    proc.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
    proc.stdin.flush()

    send(2, "tools/list")
    deadline = time.time() + 15
    while 2 not in results and time.time() < deadline:
        time.sleep(0.2)

    stop.set()
    proc.kill()

    if 2 not in results:
        print("❌ tools/list 応答なし")
        sys.exit(1)

    tools = results[2].get("result", {}).get("tools", [])
    print(f"✅ tools/list OK: {len(tools)} ツール")
    for tool in tools:
        print(f"  - {tool['name']}: {tool.get('description', '')[:70]}")
    print("\n🎉 Roblox Studio MCP 接続テスト成功")


if __name__ == "__main__":
    main()
