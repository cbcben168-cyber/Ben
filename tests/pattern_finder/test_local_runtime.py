from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import subprocess
import threading
import time

import pytest

from tv_quant.pattern_finder.runtime.config import RuntimeConfig
from tv_quant.pattern_finder.runtime.service import (
    PidRecord,
    ServiceHealth,
    _windows_pid_alive,
    _terminate_known_child,
    pid_record_matches,
    start_service,
)


ROOT = Path(__file__).resolve().parents[2]


def test_runtime_config_resolves_repository_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "PATTERN_FINDER_REPOSITORY_ROOT",
        "PATTERN_FINDER_DB_PATH",
        "PATTERN_FINDER_LOG_ROOT",
        "PATTERN_FINDER_HOST",
        "PATTERN_FINDER_PORT",
    ):
        monkeypatch.delenv(name, raising=False)

    config = RuntimeConfig.from_environment(ROOT)

    assert config.repository_root == ROOT.resolve()
    assert config.database_path == ROOT / "data/db/pattern_finder.db"
    assert config.log_root == ROOT / "logs/runtime"
    assert config.host == "127.0.0.1"
    assert config.port == 8501
    assert config.app_path == ROOT / "app/Home.py"


def test_runtime_config_rejects_non_local_default_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATTERN_FINDER_HOST", "0.0.0.0")
    with pytest.raises(ValueError, match="loopback"):
        RuntimeConfig.from_environment(ROOT)


def test_runtime_config_rejects_unbracketed_ipv6_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATTERN_FINDER_HOST", "::1")
    with pytest.raises(ValueError, match="loopback"):
        RuntimeConfig.from_environment(ROOT)


def test_pid_record_requires_repository_app_and_port_binding() -> None:
    config = RuntimeConfig.from_environment(ROOT)
    record = PidRecord(
        pid=123,
        repository_root=str(config.repository_root),
        app_path=str(config.app_path),
        host=config.host,
        port=config.port,
        started_at_utc="2026-08-25T00:00:00+00:00",
        app_run_id="run-1",
    )
    command = f'python -m streamlit run "{config.app_path}" --server.port {config.port}'

    assert pid_record_matches(record, config, command)
    assert not pid_record_matches(record, config, command.replace("Home.py", "Other.py"))
    assert not pid_record_matches(record, config, command.replace("8501", "8502"))


def test_service_health_is_not_running_on_port_only() -> None:
    state = ServiceHealth(
        running=False,
        owned_process=False,
        pid_alive=False,
        port_open=True,
        http_healthy=False,
        database_connected=True,
        schema_current=True,
        pid=None,
        detail="port occupied by another process",
    )
    assert not state.healthy


def test_windows_launchers_delegate_to_owned_runtime_cli() -> None:
    start = (ROOT / "scripts/start_pattern_finder.cmd").read_text(encoding="utf-8")
    stop = (ROOT / "scripts/stop_pattern_finder.cmd").read_text(encoding="utf-8")
    install = (ROOT / "scripts/install_desktop_launcher.cmd").read_text(
        encoding="utf-8"
    )

    assert "tv_quant.pattern_finder.runtime start" in start
    assert "tv_quant.pattern_finder.runtime stop" in stop
    assert "@(0x004B,0x7EBF,0x5F62,0x6001,0x7814,0x7A76,0x7CFB,0x7EDF)" in install
    assert "Desktop" in install
    assert "streamlit run" not in install


def test_windows_launcher_installer_is_cmd_codepage_safe() -> None:
    installer = (ROOT / "scripts/install_desktop_launcher.cmd").read_bytes()

    installer.decode("ascii")


def test_windows_pid_probe_uses_query_handle_without_signalling() -> None:
    class Kernel32:
        def __init__(self) -> None:
            self.closed: list[int] = []

        def OpenProcess(self, access: int, inherit: bool, pid: int) -> int:
            assert access == 0x1000
            assert inherit is False
            assert pid == 123
            return 77

        def GetExitCodeProcess(self, handle: int, exit_code) -> int:
            assert handle == 77
            exit_code._obj.value = 259
            return 1

        def CloseHandle(self, handle: int) -> int:
            self.closed.append(handle)
            return 1

    kernel32 = Kernel32()
    assert _windows_pid_alive(123, kernel32=kernel32)
    assert kernel32.closed == [77]


def test_startup_timeout_terminates_known_child_and_removes_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = RuntimeConfig.from_environment(ROOT)
    config = config.__class__(
        repository_root=config.repository_root,
        database_path=tmp_path / "runtime.db",
        log_root=tmp_path / "logs",
        host=config.host,
        port=18651,
        app_path=config.app_path,
        pid_path=tmp_path / "logs/pid.json",
        futu_host=config.futu_host,
        futu_port=config.futu_port,
    )

    class Process:
        pid = 43210
        terminated = False
        waited = False
        exited = False

        def poll(self):
            return 0 if self.exited else None

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float) -> int:
            self.waited = True
            self.exited = True
            return 0

    process = Process()
    monkeypatch.setenv("PATTERN_FINDER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("PATTERN_FINDER_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    monkeypatch.setattr("tv_quant.pattern_finder.runtime.service._git_commit", lambda _root: "test")
    monkeypatch.setattr("tv_quant.pattern_finder.runtime.service.subprocess.Popen", lambda *a, **k: process)
    monkeypatch.setattr(
        "tv_quant.pattern_finder.runtime.service.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0),
    )
    monkeypatch.setattr(
        "tv_quant.pattern_finder.runtime.service.service_health",
        lambda _config: ServiceHealth(False, False, False, False, False, True, True, None, "stopped"),
    )

    with pytest.raises(RuntimeError, match="health timeout"):
        start_service(config, timeout_seconds=0)

    assert process.waited and process.poll() is not None
    assert not config.pid_path.exists()


def test_windows_cleanup_falls_back_to_retained_process_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    class Process:
        pid = 54321
        exited = False
        terminate_called = False
        waits = 0

        def poll(self):
            return 0 if self.exited else None

        def wait(self, timeout: float) -> int:
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("streamlit", timeout)
            self.exited = True
            return 0

        def terminate(self) -> None:
            self.terminate_called = True

    process = Process()
    monkeypatch.setattr(
        "tv_quant.pattern_finder.runtime.service.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1),
    )

    _terminate_known_child(process, windows=True, timeout_seconds=0.01)

    assert process.terminate_called
    assert process.exited


def test_windows_stop_forces_verified_tree_when_taskkill_requires_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tv_quant.pattern_finder.runtime import service

    calls: list[list[str]] = []
    results = iter(
        (
            subprocess.CompletedProcess([], 128, stdout=b"", stderr=b"force required"),
            subprocess.CompletedProcess([], 0, stdout=b"", stderr=b""),
        )
    )

    def run(command, **_kwargs):
        calls.append(command)
        return next(results)

    monkeypatch.setattr(service.subprocess, "run", run)
    monkeypatch.setattr(service, "_pid_alive", lambda _pid: False)

    service._terminate_owned_process_tree(40472, windows=True, timeout_seconds=0)

    assert calls == [
        ["taskkill", "/PID", "40472", "/T"],
        ["taskkill", "/PID", "40472", "/T", "/F"],
    ]


def test_concurrent_starts_spawn_only_one_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = RuntimeConfig.from_environment(ROOT)
    config = base.__class__(
        repository_root=base.repository_root,
        database_path=tmp_path / "runtime.db",
        log_root=tmp_path / "logs",
        host=base.host,
        port=18652,
        app_path=base.app_path,
        pid_path=tmp_path / "logs/pid.json",
        futu_host=base.futu_host,
        futu_port=base.futu_port,
    )
    calls = 0
    serving = False
    guard = threading.Lock()

    class Process:
        pid = 65432

        def poll(self):
            return None

    process = Process()

    def popen(*args, **kwargs):
        nonlocal calls, serving
        with guard:
            calls += 1
            first = calls == 1
        if first:
            time.sleep(0.05)
            with guard:
                serving = True
        return process

    def health(_config):
        with guard:
            running = serving
        return ServiceHealth(running, running, running, running, running, True, True, process.pid if running else None, "running" if running else "stopped")

    monkeypatch.setenv("PATTERN_FINDER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("PATTERN_FINDER_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    monkeypatch.setattr("tv_quant.pattern_finder.runtime.service._git_commit", lambda _root: "test")
    monkeypatch.setattr("tv_quant.pattern_finder.runtime.service.subprocess.Popen", popen)
    monkeypatch.setattr("tv_quant.pattern_finder.runtime.service.service_health", health)

    with ThreadPoolExecutor(max_workers=2) as pool:
        states = tuple(pool.map(lambda _: start_service(config, open_browser=lambda _url: None), range(2)))

    assert calls == 1
    assert all(state.healthy for state in states)


def test_failed_child_cleanup_preserves_pid_ownership_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = RuntimeConfig.from_environment(ROOT)
    config = base.__class__(
        repository_root=base.repository_root,
        database_path=tmp_path / "runtime.db",
        log_root=tmp_path / "logs",
        host=base.host,
        port=18653,
        app_path=base.app_path,
        pid_path=tmp_path / "logs/pid.json",
        futu_host=base.futu_host,
        futu_port=base.futu_port,
    )

    class Process:
        pid = 76543

        def poll(self):
            return None

    monkeypatch.setenv("PATTERN_FINDER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("PATTERN_FINDER_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    monkeypatch.setattr("tv_quant.pattern_finder.runtime.service._git_commit", lambda _root: "test")
    monkeypatch.setattr("tv_quant.pattern_finder.runtime.service.subprocess.Popen", lambda *a, **k: Process())
    monkeypatch.setattr(
        "tv_quant.pattern_finder.runtime.service.service_health",
        lambda _config: ServiceHealth(False, False, False, False, False, True, True, None, "stopped"),
    )
    monkeypatch.setattr(
        "tv_quant.pattern_finder.runtime.service._terminate_known_child",
        lambda _process: (_ for _ in ()).throw(RuntimeError("still alive")),
    )

    with pytest.raises(RuntimeError, match="PID record preserved"):
        start_service(config, timeout_seconds=0)

    assert config.pid_path.exists()
