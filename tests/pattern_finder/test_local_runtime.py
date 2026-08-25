from __future__ import annotations

from pathlib import Path

import pytest

from tv_quant.pattern_finder.runtime.config import RuntimeConfig
from tv_quant.pattern_finder.runtime.service import (
    PidRecord,
    ServiceHealth,
    _windows_pid_alive,
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
    assert "K线形态研究系统.cmd" in install
    assert "Desktop" in install
    assert "streamlit run" not in install


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

        def poll(self):
            return None

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float) -> int:
            self.waited = True
            return 0

    process = Process()
    monkeypatch.setenv("PATTERN_FINDER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("PATTERN_FINDER_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    monkeypatch.setattr("tv_quant.pattern_finder.runtime.service.subprocess.Popen", lambda *a, **k: process)
    monkeypatch.setattr(
        "tv_quant.pattern_finder.runtime.service.service_health",
        lambda _config: ServiceHealth(False, False, False, False, False, True, True, None, "stopped"),
    )

    with pytest.raises(RuntimeError, match="health timeout"):
        start_service(config, timeout_seconds=0)

    assert process.terminated and process.waited
    assert not config.pid_path.exists()
