"""Fail-closed path containment for V2.1 provisional evidence."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath


def _validated_relative_path(relative_path: str) -> Path:
    if type(relative_path) is not str or not relative_path or "\x00" in relative_path:
        raise ValueError("relative_path: non-empty path string required")

    windows_path = PureWindowsPath(relative_path)
    posix_path = PurePosixPath(relative_path)
    if (
        windows_path.is_absolute()
        or bool(windows_path.drive)
        or posix_path.is_absolute()
    ):
        raise ValueError("relative_path: absolute, drive-relative, and UNC paths forbidden")
    if ".." in windows_path.parts or ".." in posix_path.parts:
        raise ValueError("relative_path: parent traversal forbidden")
    if windows_path.parts in ((), (".",)) or posix_path.parts in ((), (".",)):
        raise ValueError("relative_path: file or directory name required")
    return Path(relative_path)


def resolve_under_root(root: Path, relative_path: str) -> Path:
    """Resolve a relative evidence path and reject every resolved root escape."""
    root_path = Path(root)
    try:
        resolved_root = root_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("root: existing directory required") from exc
    if not resolved_root.is_dir():
        raise ValueError("root: existing directory required")

    candidate = _validated_relative_path(relative_path)
    try:
        resolved_candidate = (resolved_root / candidate).resolve(strict=False)
        resolved_candidate.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("relative_path: resolved target escapes root") from exc
    return resolved_candidate


__all__ = ("resolve_under_root",)
