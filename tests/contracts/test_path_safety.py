"""Path-containment tests for V2.1 provisional evidence."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from tv_quant.contracts.path_safety import resolve_under_root


def test_resolve_under_root_rejects_parent_traversal_absolute_and_root_escape(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()

    assert resolve_under_root(root, "evidence.json") == root / "evidence.json"
    nested = root / "nested"
    nested.mkdir()
    assert resolve_under_root(root, "nested/evidence.json") == nested / "evidence.json"

    for unsafe in (
        "../escape.json",
        "nested/../evidence.json",
        "nested/../../escape.json",
        str((tmp_path / "absolute.json").resolve()),
        "/posix/absolute.json",
    ):
        with pytest.raises(ValueError):
            resolve_under_root(root, unsafe)


def test_resolve_under_root_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    escape = root / "escape"
    try:
        escape.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        if os.name != "nt":
            pytest.skip(f"symlink creation is unavailable: {exc}")
        junction = subprocess.run(
            (
                "cmd.exe",
                "/d",
                "/c",
                "mklink",
                "/J",
                str(escape),
                str(outside),
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        if junction.returncode != 0:
            pytest.skip(f"symlink and junction creation are unavailable: {exc}")

    with pytest.raises(ValueError):
        resolve_under_root(root, "escape/owned.json")


def test_resolve_under_root_rejects_request_id_separators_and_windows_drive_unc(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()

    for unsafe in (
        r"C:drive-relative.json",
        r"C:\absolute.json",
        r"\\server\share\evidence.json",
        r"\\?\C:\evidence.json",
    ):
        with pytest.raises(ValueError):
            resolve_under_root(root, unsafe)

    from tv_quant.contracts.artifact_contract import ProvisionalEvidence

    common = {
        "evidence_kind": "validation",
        "paths": ("evidence.json",),
        "config_hash": "a" * 64,
        "data_plan_hash": "b" * 64,
        "capability_snapshot_hash": "c" * 64,
        "status": "NOT_IMPLEMENTED",
        "formal_result_published": False,
    }
    for unsafe_run_id in ("request/id", r"request\id"):
        with pytest.raises(ValueError):
            ProvisionalEvidence(run_id=unsafe_run_id, **common)


def test_resolve_under_root_rejects_ntfs_ads_and_reserved_dos_devices(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()

    for unsafe in (
        "evidence.json:stream",
        "nested/evidence.json:stream",
        "NUL",
        "nul",
        "NUL.txt",
        "CON",
        "con.TXT",
        "nested/PrN.log",
        "AUX.json",
        "COM1.data",
        "lpt9.txt",
    ):
        with pytest.raises(ValueError):
            resolve_under_root(root, unsafe)
