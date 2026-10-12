from __future__ import annotations

import argparse
from pathlib import Path
import threading
import webbrowser

import uvicorn

from .app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Futu factor progress dashboard")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--watch-dir", action="append", type=Path)
    parser.add_argument("--inbox", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    app = create_app(
        database_path=args.database,
        watch_dirs=args.watch_dir,
        inbox_dir=args.inbox,
    )
    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"Futu factor dashboard: {url}")
    print("Loopback only; no account, order, position, or trading capability.")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
