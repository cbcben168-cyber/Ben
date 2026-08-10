from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Callable, Sequence

from tv_quant.pattern_finder.cache import DEFAULT_CACHE_ROOT
from tv_quant.pattern_finder.futu_service import (
    ExpansionResult,
    refresh_universe_to_target,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely expand the Pattern Finder M3B Futu cache."
    )
    parser.add_argument("--target-size", type=int, choices=(25, 50, 100), required=True)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11111)
    return parser


def _quota_payload(quota: object | None) -> dict[str, object] | None:
    if quota is None:
        return None
    return {
        "used_quota": quota.used_quota,
        "remain_quota": quota.remain_quota,
        "detail_count": len(quota.detail_list),
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    service: Callable[..., ExpansionResult] = refresh_universe_to_target,
) -> int:
    args = build_parser().parse_args(argv)
    result = service(
        args.target_size,
        cache_root=args.cache_root,
        as_of_utc=datetime.now(UTC),
        host=args.host,
        port=args.port,
    )
    print(
        json.dumps(
            {
                "target_size": result.target_size,
                "starting_count": result.starting_count,
                "completed_symbols": list(result.completed_symbols),
                "final_count": result.final_count,
                "starting_quota": _quota_payload(result.starting_quota),
                "ending_quota": _quota_payload(result.ending_quota),
                "blocker": result.blocker,
            },
            ensure_ascii=False,
        )
    )
    return 0 if result.final_count >= result.target_size else 2


if __name__ == "__main__":
    raise SystemExit(main())
