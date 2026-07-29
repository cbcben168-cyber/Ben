"""Tests for durable, one-time V2.1 confirmation-token consumption."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path
import socket
import subprocess
import threading
from types import SimpleNamespace

import pytest

import tv_quant.contracts.confirmation as confirmation
from tv_quant.contracts.confirmation import (
    ConfirmationGrant,
    FileConfirmationStore,
    validate_and_consume,
)
from tv_quant.contracts.status_codes import BlockerCode
from tv_quant.run_manifest import sha256_bytes


TOKEN = "task12-plaintext-confirmation-token"
REQUEST_ID = "confirmation-request-task12"
CONFIG_HASH = "a" * 64
DATA_PLAN_HASH = "b" * 64
ASSUMPTIONS_HASH = "c" * 64
ISSUED_AT = "2026-07-29T01:02:00+00:00"
NOW = "2026-07-29T01:05:00+00:00"
EXPIRES_AT = "2026-07-29T01:15:00+00:00"


def _clock() -> datetime:
    return datetime.fromisoformat(NOW)


def _grant(**changes: object) -> ConfirmationGrant:
    grant = ConfirmationGrant(
        confirmation_request_id=REQUEST_ID,
        confirmation_token_hash=sha256_bytes(TOKEN.encode("utf-8")),
        bound_config_hash=CONFIG_HASH,
        bound_data_plan_hash=DATA_PLAN_HASH,
        bound_assumptions_hash=ASSUMPTIONS_HASH,
        issued_at=ISSUED_AT,
        expires_at=EXPIRES_AT,
        single_use=True,
        consumed_at=None,
    )
    return replace(grant, **changes)


def _store(path: Path, **kwargs: object) -> FileConfirmationStore:
    return FileConfirmationStore(path, _clock=_clock, **kwargs)


def _consume(
    store: FileConfirmationStore,
    token: str = TOKEN,
    config_hash: str = CONFIG_HASH,
    data_plan_hash: str = DATA_PLAN_HASH,
    assumptions_digest: str = ASSUMPTIONS_HASH,
):
    return validate_and_consume(
        token,
        config_hash,
        data_plan_hash,
        assumptions_digest,
        store,
    )


def test_missing_expired_mismatched_and_reused_token_are_rejected(tmp_path: Path) -> None:
    cases = (
        ("", _grant(), CONFIG_HASH, DATA_PLAN_HASH, ASSUMPTIONS_HASH, BlockerCode.CONFIRMATION_REQUIRED),
        (
            TOKEN,
            _grant(expires_at="2026-07-29T01:04:00+00:00"),
            CONFIG_HASH,
            DATA_PLAN_HASH,
            ASSUMPTIONS_HASH,
            BlockerCode.CONFIRMATION_EXPIRED,
        ),
        (
            "wrong-token",
            _grant(),
            CONFIG_HASH,
            DATA_PLAN_HASH,
            ASSUMPTIONS_HASH,
            BlockerCode.CONFIRMATION_HASH_MISMATCH,
        ),
        (
            TOKEN,
            _grant(),
            "d" * 64,
            DATA_PLAN_HASH,
            ASSUMPTIONS_HASH,
            BlockerCode.CONFIRMATION_HASH_MISMATCH,
        ),
        (
            TOKEN,
            _grant(),
            CONFIG_HASH,
            "e" * 64,
            ASSUMPTIONS_HASH,
            BlockerCode.CONFIRMATION_HASH_MISMATCH,
        ),
        (
            TOKEN,
            _grant(),
            CONFIG_HASH,
            DATA_PLAN_HASH,
            "f" * 64,
            BlockerCode.CONFIRMATION_HASH_MISMATCH,
        ),
    )

    for index, (token, grant, config, plan, assumptions, expected) in enumerate(cases):
        state_path = tmp_path / f"case-{index}.json"
        store = _store(state_path)
        assert store.persist_grant(grant).outcome == "SUCCESS"
        before = state_path.read_bytes()

        result = _consume(store, token, config, plan, assumptions)

        assert result.outcome == "BLOCKED"
        assert result.blocker_code is expected
        assert result.consumed_at is None
        assert state_path.read_bytes() == before

    reused_path = tmp_path / "reused.json"
    reused_store = _store(reused_path)
    assert reused_store.persist_grant(_grant()).outcome == "SUCCESS"
    assert _consume(reused_store).outcome == "SUCCESS"
    consumed_bytes = reused_path.read_bytes()

    reused = _consume(reused_store)

    assert reused.outcome == "BLOCKED"
    assert reused.blocker_code is BlockerCode.CONFIRMATION_ALREADY_USED
    assert reused.consumed_at == NOW
    assert reused_path.read_bytes() == consumed_bytes


def test_atomic_consume_allows_exactly_one_consumer(tmp_path: Path) -> None:
    state_path = tmp_path / "grant.json"
    stores = (_store(state_path), _store(state_path))
    assert stores[0].persist_grant(_grant()).outcome == "SUCCESS"
    start = threading.Barrier(3)
    results: list[object] = []

    def consume(store: FileConfirmationStore) -> None:
        start.wait(timeout=5)
        results.append(_consume(store))

    threads = [
        threading.Thread(target=consume, args=(stores[0],)),
        threading.Thread(target=consume, args=(stores[1],)),
    ]
    for thread in threads:
        thread.start()
    start.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 2
    assert sum(result.outcome == "SUCCESS" for result in results) == 1
    losers = [result for result in results if result.outcome == "BLOCKED"]
    assert len(losers) == 1
    assert losers[0].blocker_code is BlockerCode.CONFIRMATION_ALREADY_USED
    assert losers[0].consumed_at == NOW


def test_lock_wait_crossing_expiry_is_rejected_without_mutation(tmp_path: Path) -> None:
    state_path = tmp_path / "grant.json"
    assert _store(state_path).persist_grant(_grant()).outcome == "SUCCESS"
    issued_bytes = state_path.read_bytes()
    current = {"now": datetime.fromisoformat("2026-07-29T01:14:59+00:00")}

    class ExpiryCrossingBackend:
        def acquire(self, _handle: object) -> None:
            current["now"] = datetime.fromisoformat("2026-07-29T01:15:01+00:00")

        def release(self, _handle: object) -> None:
            return None

    store = FileConfirmationStore(
        state_path,
        _clock=lambda: current["now"],
        _lock_backend=ExpiryCrossingBackend(),
    )

    result = _consume(store)

    assert result.outcome == "BLOCKED"
    assert result.blocker_code is BlockerCode.CONFIRMATION_EXPIRED
    assert result.evaluated_at == "2026-07-29T01:15:01+00:00"
    assert result.consumed_at is None
    assert state_path.read_bytes() == issued_bytes


def test_crash_before_replace_leaves_grant_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "grant.json"
    store = _store(state_path)
    assert store.persist_grant(_grant()).outcome == "SUCCESS"
    issued_bytes = state_path.read_bytes()
    real_replace = confirmation.os.replace

    def fail_before_replace(_source: object, _target: object) -> None:
        raise OSError("simulated pre-replace crash")

    monkeypatch.setattr(confirmation.os, "replace", fail_before_replace)
    failed = _consume(store)
    assert failed.blocker_code is BlockerCode.CONFIRMATION_STORAGE_BLOCKER
    assert state_path.read_bytes() == issued_bytes
    assert not list(tmp_path.glob("*.tmp"))

    monkeypatch.setattr(confirmation.os, "replace", real_replace)
    assert _consume(store).outcome == "SUCCESS"


def test_crash_after_replace_keeps_grant_consumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "grant.json"
    store = _store(state_path)
    assert store.persist_grant(_grant()).outcome == "SUCCESS"
    real_replace = confirmation.os.replace

    def fail_after_replace(source: object, target: object) -> None:
        real_replace(source, target)
        raise OSError("simulated post-replace crash")

    monkeypatch.setattr(confirmation.os, "replace", fail_after_replace)
    failed = _consume(store)
    assert failed.blocker_code is BlockerCode.CONFIRMATION_STORAGE_BLOCKER

    monkeypatch.setattr(confirmation.os, "replace", real_replace)
    reused = _consume(store)
    assert reused.blocker_code is BlockerCode.CONFIRMATION_ALREADY_USED
    assert reused.consumed_at == NOW


def test_lock_release_occurs_after_success_and_failure(tmp_path: Path) -> None:
    class RecordingBackend:
        def __init__(self) -> None:
            self.events: list[str] = []

        def acquire(self, _handle: object) -> None:
            self.events.append("acquire")

        def release(self, _handle: object) -> None:
            self.events.append("release")

    backend = RecordingBackend()
    store = _store(tmp_path / "grant.json", _lock_backend=backend)
    assert store.persist_grant(_grant()).outcome == "SUCCESS"
    assert backend.events == ["acquire", "release"]

    backend.events.clear()
    assert _consume(store, token="wrong-token").outcome == "BLOCKED"
    assert backend.events == ["acquire", "release"]

    backend.events.clear()
    assert _consume(store).outcome == "SUCCESS"
    assert backend.events == ["acquire", "release"]


def test_windows_lock_backend_uses_msvcrt_contract() -> None:
    calls: list[tuple[int, int, int]] = []
    fake_msvcrt = SimpleNamespace(
        LK_NBLCK=1,
        LK_UNLCK=2,
        locking=lambda fd, mode, size: calls.append((fd, mode, size)),
    )
    handle = SimpleNamespace(fileno=lambda: 42, seek=lambda position: None)
    backend = confirmation._WindowsLockBackend(fake_msvcrt, timeout_seconds=0)

    backend.acquire(handle)
    backend.release(handle)

    assert calls == [(42, fake_msvcrt.LK_NBLCK, 1), (42, fake_msvcrt.LK_UNLCK, 1)]


def test_posix_lock_backend_uses_fcntl_contract() -> None:
    calls: list[tuple[int, int]] = []
    fake_fcntl = SimpleNamespace(
        LOCK_EX=1,
        LOCK_NB=2,
        LOCK_UN=4,
        flock=lambda fd, mode: calls.append((fd, mode)),
    )
    handle = SimpleNamespace(fileno=lambda: 43)
    backend = confirmation._PosixLockBackend(fake_fcntl, timeout_seconds=0)

    backend.acquire(handle)
    backend.release(handle)

    assert calls == [
        (43, fake_fcntl.LOCK_EX | fake_fcntl.LOCK_NB),
        (43, fake_fcntl.LOCK_UN),
    ]


def test_unsupported_lock_backend_returns_storage_blocker(tmp_path: Path) -> None:
    store = _store(
        tmp_path / "grant.json",
        _lock_backend=confirmation._UnsupportedLockBackend(),
    )

    persisted = store.persist_grant(_grant())
    consumed = _consume(store)

    assert persisted.blocker_code is BlockerCode.CONFIRMATION_STORAGE_BLOCKER
    assert consumed.blocker_code is BlockerCode.CONFIRMATION_STORAGE_BLOCKER


def test_storage_read_failure_returns_redacted_storage_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "grant.json"
    store = _store(state_path)
    assert store.persist_grant(_grant()).outcome == "SUCCESS"

    def fail_read(_path: Path, **_kwargs: object) -> str:
        raise PermissionError(f"storage failure containing {TOKEN}")

    monkeypatch.setattr(Path, "read_text", fail_read)
    result = _consume(store)

    assert result.blocker_code is BlockerCode.CONFIRMATION_STORAGE_BLOCKER
    assert TOKEN not in repr(result)


@pytest.mark.parametrize("config_hash", ("d" * 64, "malformed"))
def test_all_three_binding_comparisons_execute_without_short_circuit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_hash: str,
) -> None:
    state_path = tmp_path / "grant.json"
    store = _store(state_path)
    grant = _grant()
    assert store.persist_grant(grant).outcome == "SUCCESS"
    compare_calls: list[tuple[object, object]] = []
    real_compare = confirmation.hmac.compare_digest

    def record_compare(left: object, right: object) -> bool:
        compare_calls.append((left, right))
        return real_compare(left, right)  # type: ignore[arg-type]

    monkeypatch.setattr(confirmation.hmac, "compare_digest", record_compare)

    result = _consume(store, config_hash=config_hash)

    assert result.blocker_code is BlockerCode.CONFIRMATION_HASH_MISMATCH
    assert len(compare_calls) == 4
    assert [right for _left, right in compare_calls[1:]] == [
        CONFIG_HASH,
        DATA_PLAN_HASH,
        ASSUMPTIONS_HASH,
    ]
    assert all(
        type(left) is str and len(left) == 64 for left, _right in compare_calls[1:]
    )


def test_unpaired_surrogate_token_returns_redacted_hash_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_path = tmp_path / "grant.json"
    store = _store(state_path)
    assert store.persist_grant(_grant()).outcome == "SUCCESS"
    before = state_path.read_bytes()
    malformed_token = "synthetic-secret-\ud800-token"

    result = _consume(store, token=malformed_token)
    captured = capsys.readouterr()

    assert result.blocker_code is BlockerCode.CONFIRMATION_HASH_MISMATCH
    assert state_path.read_bytes() == before
    assert malformed_token not in repr(result)
    assert malformed_token not in captured.out
    assert malformed_token not in captured.err


def test_audit_record_never_contains_plaintext_token(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_path = tmp_path / "grant.json"
    store = _store(state_path)
    persisted = store.persist_grant(_grant())
    success = _consume(store)
    reused = _consume(store)
    captured = capsys.readouterr()

    for record in (persisted, success, reused):
        rendered = json.dumps(asdict(record), sort_keys=True, default=str)
        assert TOKEN not in rendered
        assert TOKEN not in repr(record)
        assert "confirmation_token" not in asdict(record)
        assert "confirmation_token_hash" not in asdict(record)
    assert TOKEN not in state_path.read_text(encoding="utf-8")
    assert TOKEN not in captured.out
    assert TOKEN not in captured.err
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(state) == {"schema_version", "state_version", "grant"}
    assert set(state["grant"]) == {
        "confirmation_request_id",
        "confirmation_token_hash",
        "bound_config_hash",
        "bound_data_plan_hash",
        "bound_assumptions_hash",
        "issued_at",
        "expires_at",
        "single_use",
        "consumed_at",
    }
    assert not {
        "token",
        "user",
        "chat",
        "host",
        "pid",
        "environment",
        "provider",
        "path",
    }.intersection(state["grant"])


@pytest.mark.parametrize(
    "payload",
    (
        "{",
        json.dumps({"schema_version": "v2.1", "state_version": 1}),
        json.dumps(
            {
                "schema_version": "v2.1",
                "state_version": 1,
                "grant": {},
                "unknown": True,
            }
        ),
        json.dumps({"schema_version": "v9", "state_version": 1, "grant": {}}),
        json.dumps({"schema_version": "v2.1", "state_version": 2, "grant": {}}),
    ),
)
def test_malformed_unknown_missing_and_unsupported_state_is_invalid_without_mutation(
    tmp_path: Path, payload: str
) -> None:
    state_path = tmp_path / "grant.json"
    state_path.write_text(payload, encoding="utf-8")
    before = state_path.read_bytes()

    result = _consume(_store(state_path))

    assert result.outcome == "BLOCKED"
    assert result.blocker_code is BlockerCode.CONFIRMATION_INVALID
    assert state_path.read_bytes() == before


def test_missing_official_state_is_invalid(tmp_path: Path) -> None:
    result = _consume(_store(tmp_path / "missing.json"))

    assert result.outcome == "BLOCKED"
    assert result.blocker_code is BlockerCode.CONFIRMATION_INVALID


@pytest.mark.parametrize("state_version", (True, 1.0))
def test_state_version_requires_exact_integer_without_mutation(
    tmp_path: Path, state_version: object
) -> None:
    state_path = tmp_path / "grant.json"
    store = _store(state_path)
    assert store.persist_grant(_grant()).outcome == "SUCCESS"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["state_version"] = state_version
    state_path.write_text(json.dumps(payload), encoding="utf-8")
    before = state_path.read_bytes()

    result = _consume(store)

    assert result.blocker_code is BlockerCode.CONFIRMATION_INVALID
    assert result.consumed_at is None
    assert state_path.read_bytes() == before


def test_consumed_state_is_rejected_before_single_use_validation(tmp_path: Path) -> None:
    state_path = tmp_path / "grant.json"
    store = _store(state_path)
    assert store.persist_grant(_grant()).outcome == "SUCCESS"
    assert _consume(store).outcome == "SUCCESS"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["grant"]["single_use"] = False
    state_path.write_text(json.dumps(payload), encoding="utf-8")

    result = _consume(store)

    assert result.blocker_code is BlockerCode.CONFIRMATION_ALREADY_USED
    assert result.consumed_at == NOW


def test_caller_cannot_inject_replacement_token_hash(tmp_path: Path) -> None:
    state_path = tmp_path / "grant.json"
    store = _store(state_path)
    assert store.persist_grant(_grant()).outcome == "SUCCESS"
    before = state_path.read_bytes()

    assert "confirmation_token_hash" not in inspect.signature(validate_and_consume).parameters
    with pytest.raises(TypeError):
        validate_and_consume(
            TOKEN,
            CONFIG_HASH,
            DATA_PLAN_HASH,
            ASSUMPTIONS_HASH,
            store,
            confirmation_token_hash="f" * 64,  # type: ignore[call-arg]
        )
    assert state_path.read_bytes() == before


def test_existing_official_state_cannot_be_replaced(tmp_path: Path) -> None:
    state_path = tmp_path / "grant.json"
    store = _store(state_path)
    assert store.persist_grant(_grant()).outcome == "SUCCESS"
    before = state_path.read_bytes()

    replacement = store.persist_grant(
        _grant(confirmation_token_hash=sha256_bytes(b"replacement-token"))
    )

    assert replacement.blocker_code is BlockerCode.CONFIRMATION_INVALID
    assert state_path.read_bytes() == before


def test_store_has_no_network_process_or_backtest_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: pytest.fail("network side effect"),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("process/provider side effect"),
    )
    store = _store(tmp_path / "grant.json")

    assert store.persist_grant(_grant()).outcome == "SUCCESS"
    assert _consume(store).outcome == "SUCCESS"
