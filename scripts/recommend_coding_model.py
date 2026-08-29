"""Print a deterministic Codex model recommendation as JSON."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Sequence

from tv_quant.model_routing import recommend_model


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, help="Coding task description")
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="Repository-relative changed or expected path; repeat as needed",
    )
    arguments = parser.parse_args(argv)
    decision = recommend_model(arguments.task, arguments.path)
    print(json.dumps(asdict(decision), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
