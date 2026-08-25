"""Validated, relocatable local runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _resolved_path(root: Path, value: str | None, default: str) -> Path:
    path = Path(value) if value else Path(default)
    return (path if path.is_absolute() else root / path).resolve()


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    repository_root: Path
    database_path: Path
    log_root: Path
    host: str
    port: int
    app_path: Path
    pid_path: Path
    futu_host: str
    futu_port: int

    @classmethod
    def from_environment(cls, repository_root: str | Path | None = None) -> "RuntimeConfig":
        configured_root = os.getenv("PATTERN_FINDER_REPOSITORY_ROOT")
        root = Path(configured_root or repository_root or Path(__file__).resolve().parents[4]).resolve()
        if not (root / "app/Home.py").is_file() or not (root / "src/tv_quant").is_dir():
            raise ValueError(f"repository root is invalid: {root}")
        host = os.getenv("PATTERN_FINDER_HOST", "127.0.0.1").strip()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("PATTERN_FINDER_HOST must be a loopback address")
        try:
            port = int(os.getenv("PATTERN_FINDER_PORT", "8501"))
            futu_port = int(os.getenv("FUTU_OPEND_PORT", "11111"))
        except ValueError as error:
            raise ValueError("runtime ports must be integers") from error
        if not 1 <= port <= 65535 or not 1 <= futu_port <= 65535:
            raise ValueError("runtime ports must be between 1 and 65535")
        log_root = _resolved_path(root, os.getenv("PATTERN_FINDER_LOG_ROOT"), "logs/runtime")
        return cls(
            repository_root=root,
            database_path=_resolved_path(root, os.getenv("PATTERN_FINDER_DB_PATH"), "data/db/pattern_finder.db"),
            log_root=log_root,
            host=host,
            port=port,
            app_path=(root / "app/Home.py").resolve(),
            pid_path=log_root / "pattern_finder.pid.json",
            futu_host=os.getenv("FUTU_OPEND_HOST", "127.0.0.1").strip(),
            futu_port=futu_port,
        )
