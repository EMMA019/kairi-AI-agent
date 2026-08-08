#!/usr/bin/env python3
"""
Kairi Desktop launcher — binds 127.0.0.1 only; KAIRI_RELEASE=1 hides OpenAPI.
Port 8000 busy → try 8001..8019 automatically.
"""
import sys
import os
import socket
import time
import webbrowser
import threading
from pathlib import Path

os.environ.setdefault("KAIRI_RELEASE", "1")
os.environ.setdefault("ALLOW_OPEN_CORS", "0")
# Radar / briefing schedulers stay off in release unless explicitly enabled
os.environ.setdefault("KAIRI_ENABLE_SCHEDULERS", "0")

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def pick_port(preferred: int = 8000, attempts: int = 20) -> int:
    for port in range(preferred, preferred + attempts):
        if _port_free("127.0.0.1", port):
            return port
    raise RuntimeError(
        f"No free port in range {preferred}-{preferred + attempts - 1}. "
        "Close the other app or set KAIRI_PORT."
    )


def run_server(port=8000):
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
        reload=False,
    )


def main():
    preferred = int(os.environ.get("KAIRI_PORT", "8000"))
    # If KAIRI_PORT is set explicitly, still fall back when occupied unless KAIRI_PORT_STRICT=1
    strict = os.environ.get("KAIRI_PORT_STRICT", "").strip() in ("1", "true", "TRUE", "yes")
    if strict:
        if not _port_free("127.0.0.1", preferred):
            print(f"[ERROR] Port {preferred} is in use (KAIRI_PORT_STRICT=1).")
            sys.exit(1)
        port = preferred
    else:
        port = pick_port(preferred)
        if port != preferred:
            print(f"[info] Port {preferred} busy - using {port} instead.")

    # Remember for support / scripts
    try:
        port_file = BACKEND_DIR / "storage" / "runtime_port.txt"
        port_file.parent.mkdir(parents=True, exist_ok=True)
        port_file.write_text(str(port), encoding="utf-8")
    except Exception:
        pass

    print(f"Starting Kairi Desktop on http://127.0.0.1:{port}/ ...")
    print("(First run: paste DeepSeek API key in the browser wizard. Data stays on this PC.)")

    server_thread = threading.Thread(target=run_server, args=(port,), daemon=True)
    server_thread.start()

    time.sleep(2.0)
    app_url = f"http://127.0.0.1:{port}/"
    print(f"Opening {app_url}")
    webbrowser.open(app_url)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down Kairi Desktop...")
        sys.exit(0)


if __name__ == "__main__":
    main()
