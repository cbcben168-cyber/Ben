"""Command-line entry point used by Windows launchers."""

from __future__ import annotations

import argparse
import json

from .config import RuntimeConfig
from .service import service_health, start_service, stop_service


def main() -> int:
    parser = argparse.ArgumentParser(prog="pattern-finder-runtime")
    parser.add_argument("command", choices=("migrate", "health", "start", "stop"))
    args = parser.parse_args()
    config = RuntimeConfig.from_environment()
    if args.command == "migrate":
        from tv_quant.pattern_finder.persistence.bootstrap import initialize_local_foundation
        print(initialize_local_foundation(config).current_version())
        return 0
    if args.command == "health":
        state = service_health(config)
        print(json.dumps({"healthy": state.healthy, "detail": state.detail, "pid": state.pid}))
        return 0 if state.healthy else 1
    if args.command == "start":
        start_service(config)
        return 0
    return 0 if stop_service(config) else 1


if __name__ == "__main__":
    raise SystemExit(main())
