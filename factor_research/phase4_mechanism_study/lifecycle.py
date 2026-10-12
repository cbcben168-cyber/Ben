from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .structural_preflight import PHASE41_COMMIT, StructuralPreflightError, verify_preflight_identity


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, check=False, capture_output=True, text=True
    )


def verify_post_checkpoint_identity(
    registration_path: Path | None = None,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Verify frozen source identity plus a descendant-or-equal Git checkpoint."""

    registration = verify_preflight_identity(registration_path, verify_git=False)
    if registration.get("phase41_commit") != PHASE41_COMMIT:
        raise StructuralPreflightError("PHASE41_COMMIT_IDENTITY_MISMATCH")
    root = repo_root or _repo_root()
    head_result = _git(root, "rev-parse", "HEAD")
    if head_result.returncode:
        raise StructuralPreflightError("GIT_HEAD_UNAVAILABLE")
    ancestor = _git(root, "merge-base", "--is-ancestor", PHASE41_COMMIT, head_result.stdout.strip())
    if ancestor.returncode:
        raise StructuralPreflightError("PHASE41_CHECKPOINT_NOT_ANCESTOR")
    return {
        **registration,
        "current_head": head_result.stdout.strip(),
        "phase41_checkpoint_relation": "ANCESTOR_OR_EQUAL",
    }
