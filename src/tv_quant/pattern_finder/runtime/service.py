"""Owned Streamlit process lifecycle and compound health checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Callable
from urllib.request import urlopen
from uuid import uuid4
import webbrowser

from .config import RuntimeConfig


@dataclass(frozen=True, slots=True)
class PidRecord:
    pid: int
    repository_root: str
    app_path: str
    host: str
    port: int
    started_at_utc: str
    app_run_id: str


@dataclass(frozen=True, slots=True)
class ServiceHealth:
    running: bool
    owned_process: bool
    pid_alive: bool
    port_open: bool
    http_healthy: bool
    database_connected: bool
    schema_current: bool
    pid: int | None
    detail: str

    @property
    def healthy(self) -> bool:
        return all(
            (
                self.running,
                self.owned_process,
                self.pid_alive,
                self.port_open,
                self.http_healthy,
                self.database_connected,
                self.schema_current,
            )
        )


def pid_record_matches(record: PidRecord, config: RuntimeConfig, command_line: str) -> bool:
    normalized = command_line.replace("\\", "/").casefold()
    app = str(config.app_path).replace("\\", "/").casefold()
    return (
        Path(record.repository_root).resolve() == config.repository_root
        and Path(record.app_path).resolve() == config.app_path
        and record.host == config.host
        and record.port == config.port
        and app in normalized
        and str(config.port) in normalized
        and "streamlit" in normalized
    )


def _read_pid(path: Path) -> PidRecord | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return PidRecord(**value)
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_pid(path: Path, record: PidRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(record), sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _runtime_log(config: RuntimeConfig, event: str, detail: str) -> None:
    config.log_root.mkdir(parents=True, exist_ok=True)
    path = config.log_root / f"runtime-{datetime.now(UTC):%Y%m%d}.log"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"{datetime.now(UTC).isoformat()} event={event} {detail}\n"
        )


def _git_commit(repository_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repository_root,
            text=True,
            timeout=3,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


def _windows_pid_alive(pid: int, *, kernel32: object | None = None) -> bool:
    """Query process state through a read-only Windows handle."""
    if pid <= 0:
        return False
    api = kernel32 if kernel32 is not None else ctypes.windll.kernel32  # type: ignore[attr-defined]
    if kernel32 is None:
        api.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        api.OpenProcess.restype = wintypes.HANDLE
        api.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        api.GetExitCodeProcess.restype = wintypes.BOOL
        api.CloseHandle.argtypes = (wintypes.HANDLE,)
        api.CloseHandle.restype = wintypes.BOOL
    handle = api.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not api.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == 259  # STILL_ACTIVE
    finally:
        api.CloseHandle(handle)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _remove_pid_record(config: RuntimeConfig, expected_pid: int) -> None:
    record = _read_pid(config.pid_path)
    if record is not None and record.pid != expected_pid:
        return
    try:
        config.pid_path.unlink()
    except FileNotFoundError:
        pass


def _terminate_known_child(process: subprocess.Popen[object], *, timeout_seconds: float = 5.0) -> None:
    """Terminate only the exact child handle returned by this start attempt."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            process.kill()
            process.wait(timeout=timeout_seconds)


def _command_line(pid: int) -> str:
    proc_path = Path(f"/proc/{pid}/cmdline")
    if proc_path.is_file():
        try:
            return proc_path.read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            return ""
    if os.name == "nt":
        command = [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine",
        ]
        try:
            return subprocess.check_output(command, text=True, timeout=5).strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    return ""


def _port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_healthy(config: RuntimeConfig, timeout: float = 1.0) -> bool:
    try:
        with urlopen(f"http://{config.host}:{config.port}/_stcore/health", timeout=timeout) as response:
            return response.status == 200 and response.read(32).strip().lower() == b"ok"
    except OSError:
        return False


def _database_health(config: RuntimeConfig) -> tuple[bool, bool]:
    try:
        from tv_quant.pattern_finder.persistence.database import SqliteDatabase

        database = SqliteDatabase(config.database_path)
        version = database.current_version()
        if version != database.latest_version:
            return True, False
        database.validate_schema()
        return True, True
    except Exception:
        return False, False


def service_health(config: RuntimeConfig) -> ServiceHealth:
    record = _read_pid(config.pid_path)
    pid_alive = record is not None and _pid_alive(record.pid)
    command = _command_line(record.pid) if pid_alive and record is not None else ""
    owned = record is not None and pid_alive and pid_record_matches(record, config, command)
    port_open = _port_open(config.host, config.port)
    http_ok = _http_healthy(config) if port_open else False
    db_ok, schema_ok = _database_health(config)
    running = bool(owned and http_ok)
    if port_open and not owned:
        detail = "configured port is occupied by a process not owned by this repository"
    elif record is not None and not pid_alive:
        detail = "stale PID record"
    elif running:
        detail = "running"
    else:
        detail = "stopped"
    return ServiceHealth(running, owned, pid_alive, port_open, http_ok, db_ok, schema_ok, record.pid if record else None, detail)


def start_service(
    config: RuntimeConfig,
    *,
    open_browser: Callable[[str], object] = webbrowser.open,
    timeout_seconds: float = 30.0,
) -> ServiceHealth:
    from tv_quant.pattern_finder.persistence.bootstrap import initialize_local_foundation
    from tv_quant.pattern_finder.persistence.repositories import SystemRepository

    database = initialize_local_foundation(config)
    existing = service_health(config)
    url = f"http://{config.host}:{config.port}"
    if existing.healthy:
        open_browser(url)
        return existing
    if existing.port_open:
        raise RuntimeError(existing.detail)
    config.log_root.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid4())
    app_version = "pattern-finder-local/v1"
    git_commit = _git_commit(config.repository_root)
    log_path = config.log_root / f"runtime-{datetime.now(UTC):%Y%m%d}.log"
    command = [
        sys.executable, "-m", "streamlit", "run", str(config.app_path),
        "--server.address", config.host, "--server.port", str(config.port),
        "--server.headless", "true", "--browser.gatherUsageStats", "false",
    ]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(config.repository_root / "src")
    environment["PATTERN_FINDER_REPOSITORY_ROOT"] = str(config.repository_root)
    environment["PATTERN_FINDER_DB_PATH"] = str(config.database_path)
    handle = log_path.open("a", encoding="utf-8")
    try:
        process = subprocess.Popen(command, cwd=config.repository_root, env=environment, stdout=handle, stderr=subprocess.STDOUT)
    finally:
        handle.close()
    record = PidRecord(process.pid, str(config.repository_root), str(config.app_path), config.host, config.port, datetime.now(UTC).isoformat(), run_id)
    run_started = False
    try:
        _write_pid(config.pid_path, record)
        _runtime_log(
            config,
            "start",
            f"run_id={run_id} pid={process.pid} port={config.port} app_version={app_version} "
            f"git_commit={git_commit} db={config.database_path} schema={database.latest_version}",
        )
        SystemRepository(database).start_app_run(
            run_id,
            process.pid,
            config.port,
            app_version=app_version,
            git_commit=git_commit,
        )
        run_started = True
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Streamlit startup failed; inspect {log_path}")
            state = service_health(config)
            if state.healthy:
                open_browser(url)
                return state
            time.sleep(0.2)
        raise RuntimeError(f"Streamlit health timeout; inspect {log_path}")
    except BaseException as error:
        try:
            _terminate_known_child(process)
        except Exception:
            pass
        try:
            _remove_pid_record(config, process.pid)
        except Exception:
            pass
        if run_started:
            try:
                SystemRepository(database).finish_app_run(run_id, "ERROR", str(error))
            except Exception:
                pass
        try:
            _runtime_log(config, "start_error", f"run_id={run_id} pid={process.pid} error={type(error).__name__}")
        except Exception:
            pass
        raise


def stop_service(config: RuntimeConfig, *, timeout_seconds: float = 10.0) -> bool:
    record = _read_pid(config.pid_path)
    if record is None or not _pid_alive(record.pid):
        return False
    if not pid_record_matches(record, config, _command_line(record.pid)):
        raise RuntimeError("refusing to stop a process not owned by this repository")
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(record.pid), "/T"], check=False, capture_output=True)
    else:
        os.kill(record.pid, 15)
    deadline = time.monotonic() + timeout_seconds
    while _pid_alive(record.pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    if _pid_alive(record.pid):
        raise RuntimeError("owned process did not stop before timeout")
    try:
        config.pid_path.unlink()
    except FileNotFoundError:
        pass
    try:
        from tv_quant.pattern_finder.persistence.database import SqliteDatabase
        from tv_quant.pattern_finder.persistence.repositories import SystemRepository
        SystemRepository(SqliteDatabase(config.database_path)).finish_app_run(record.app_run_id, "STOPPED", None)
    except Exception:
        pass
    _runtime_log(
        config,
        "stop",
        f"run_id={record.app_run_id} pid={record.pid} port={record.port} db={config.database_path}",
    )
    return True
