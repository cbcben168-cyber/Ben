from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from threading import Barrier

import duckdb
import pytest

from tv_quant.ff.database import ActiveScanError, FFDatabase, FFTransaction


UTC = timezone.utc
SCAN_DAY = date(2026, 7, 17)
NOW = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)
T1 = date(2026, 9, 18)
T2 = date(2026, 10, 16)


def scan_run(run_id: str, **changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "scan_run_id": run_id,
        "strategy_version": "ff-v1",
        "universe_version": "universe-v1",
        "logical_session_date": SCAN_DAY,
        "status": "ACTIVE",
        "owner_id": "worker-1",
        "claimed_at_utc": NOW,
        "lease_expires_at_utc": NOW + timedelta(minutes=15),
        "created_at_utc": NOW,
    }
    values.update(changes)
    return values


def signal(signal_id: str, **changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "signal_id": signal_id,
        "scan_run_id": "run-1",
        "strategy_version": "ff-v1",
        "scan_date": SCAN_DAY,
        "ticker": "SPY",
        "t1_expiry": T1,
        "t2_expiry": T2,
        "status": "BUY_CANDIDATE",
        "sigma_1": 0.20,
        "sigma_2": 0.24,
        "forward_variance": 0.08,
        "sigma_forward": 0.28,
        "ff": 0.25,
        "relative_spread": 0.10,
        "created_at_utc": NOW,
        "updated_at_utc": NOW,
    }
    values.update(changes)
    return values


def notification(notification_id: str, signal_id: str, **changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "notification_id": notification_id,
        "idempotency_key": f"mail:{signal_id}",
        "channel": "gmail",
        "record_type": "signal",
        "record_id": signal_id,
        "status": "PENDING",
        "payload_json": {"signal_id": signal_id},
        "attempt_count": 0,
        "created_at_utc": NOW,
        "updated_at_utc": NOW,
    }
    values.update(changes)
    return values


def sync_job(sync_id: str, **changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "sync_outbox_id": sync_id,
        "target": "sites",
        "record_type": "signal",
        "record_id": "sig-1",
        "schema_version": "1",
        "payload_json": {"signal_id": "sig-1"},
        "status": "PENDING",
        "attempt_count": 0,
        "created_at_utc": NOW,
        "updated_at_utc": NOW,
    }
    values.update(changes)
    return values


def option_snapshot(snapshot_id: str, **changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "option_snapshot_id": snapshot_id,
        "scan_run_id": "run-1",
        "ticker": "SPY",
        "expiry": T1,
        "option_type": "CALL",
        "strike": 600.0,
        "bid": 1.0,
        "ask": 1.1,
        "iv": 0.20,
        "delta": 0.50,
        "open_interest": 500,
        "volume": 50,
        "contract_symbol": "SPY260918C00600000",
        "captured_at_utc": NOW,
    }
    values.update(changes)
    return values


def option_liquidity(liquidity_id: str, **changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "liquidity_id": liquidity_id,
        "logical_date": SCAN_DAY,
        "ticker": "SPY",
        "total_option_volume": 12_500,
        "observed_at_utc": NOW,
    }
    values.update(changes)
    return values


def migrated_database(tmp_path) -> FFDatabase:
    db = FFDatabase(tmp_path / "ff.duckdb")
    db.migrate()
    return db


def persist_complete_scan(db: FFDatabase, signal_id: str, idempotency_key: str) -> None:
    with db.scan_transaction() as tx:
        tx.insert_scan_run(scan_run("run-1"))
        tx.insert_signal(signal(signal_id))
        tx.enqueue_notification(
            notification(f"notification-{signal_id}", signal_id, idempotency_key=idempotency_key)
        )


def test_migrate_creates_exactly_the_required_business_tables(tmp_path):
    db = migrated_database(tmp_path)

    assert set(db.table_names()) == {
        "audit_events",
        "earnings_events",
        "notifications",
        "option_liquidity_daily",
        "option_snapshots",
        "position_legs",
        "positions",
        "scan_results",
        "scan_runs",
        "signals",
        "strategy_versions",
        "sync_outbox",
        "universe_members",
        "universe_versions",
    }


def test_scan_transaction_rolls_back_every_business_and_outbox_row(tmp_path):
    db = migrated_database(tmp_path)

    with pytest.raises(RuntimeError, match="abort"):
        with db.scan_transaction() as tx:
            tx.insert_scan_run(scan_run("run-1"))
            tx.insert_signal(signal("sig-1"))
            tx.enqueue_notification(notification("mail-1", "sig-1"))
            raise RuntimeError("abort")

    assert db.count("scan_runs") == 0
    assert db.count("signals") == 0
    assert db.count("notifications") == 0


def test_deterministic_keys_prevent_duplicate_signal_and_outbox(tmp_path):
    db = migrated_database(tmp_path)

    persist_complete_scan(db, signal_id="sig-1", idempotency_key="mail:sig-1")
    persist_complete_scan(db, signal_id="sig-1", idempotency_key="mail:sig-1")

    assert db.count("signals") == 1
    assert db.count("notifications") == 1


def test_numeric_columns_reject_string_sentinels_before_duckdb_coercion(tmp_path):
    db = migrated_database(tmp_path)

    with pytest.raises(ValueError, match="signals.ff must be numeric"):
        with db.scan_transaction() as tx:
            tx.insert_scan_run(scan_run("run-1"))
            tx.insert_signal(signal("sig-1", ff="N/A"))

    assert db.count("scan_runs") == 0
    assert db.count("signals") == 0


def test_sync_outbox_is_idempotent_on_target_record_and_update_time(tmp_path):
    db = migrated_database(tmp_path)

    db.enqueue_sync(sync_job("sync-1"))
    db.enqueue_sync(sync_job("sync-2"))

    assert db.count("sync_outbox") == 1


def test_second_active_scan_for_the_same_strategy_session_is_rejected(tmp_path):
    db = migrated_database(tmp_path)
    assert db.claim_scan(scan_run("run-1"), now_utc=NOW) == "run-1"

    with pytest.raises(ActiveScanError, match="already active"):
        db.claim_scan(
            scan_run("run-2", owner_id="worker-2", claimed_at_utc=NOW + timedelta(minutes=1)),
            now_utc=NOW + timedelta(minutes=1),
        )

    assert db.count("scan_runs") == 1
    assert db.count("audit_events") == 0


def test_expired_active_scan_is_taken_over_and_audited_atomically(tmp_path):
    db = migrated_database(tmp_path)
    db.claim_scan(
        scan_run(
            "run-1",
            claimed_at_utc=NOW - timedelta(minutes=20),
            lease_expires_at_utc=NOW - timedelta(minutes=5),
        ),
        now_utc=NOW - timedelta(minutes=20),
    )

    claimed_run_id = db.claim_scan(
        scan_run("run-2", owner_id="worker-2"),
        now_utc=NOW,
    )

    assert claimed_run_id == "run-1"
    assert db.fetch_one("scan_runs", scan_run_id="run-1").owner_id == "worker-2"
    assert db.count("scan_runs") == 1
    audit = db.fetch_one("audit_events", record_id="run-1")
    assert audit is not None
    assert audit.event_type == "SCAN_LEASE_TAKEN_OVER"


def test_commit_scan_compare_and_set_clears_the_active_lease(tmp_path):
    db = migrated_database(tmp_path)
    db.claim_scan(scan_run("run-1"), now_utc=NOW)

    assert db.commit_scan(
        "run-1",
        owner_id="worker-1",
        completed_at_utc=NOW + timedelta(minutes=2),
        now_utc=NOW + timedelta(minutes=2),
    )
    completed = db.fetch_one("scan_runs", scan_run_id="run-1")
    assert completed.status == "COMMITTED"
    assert completed.lease_expires_at_utc is None
    assert not db.commit_scan(
        "run-1",
        owner_id="worker-1",
        completed_at_utc=NOW + timedelta(minutes=3),
        now_utc=NOW + timedelta(minutes=3),
    )


def test_expired_lease_owner_cannot_commit_scan(tmp_path):
    db = migrated_database(tmp_path)
    db.claim_scan(scan_run("run-1"), now_utc=NOW)

    assert not db.commit_scan(
        "run-1",
        owner_id="worker-1",
        completed_at_utc=NOW + timedelta(minutes=16),
        now_utc=NOW + timedelta(minutes=16),
    )
    assert db.fetch_one("scan_runs", scan_run_id="run-1").status == "ACTIVE"


def test_backdated_completion_cannot_bypass_an_expired_lease(tmp_path):
    db = migrated_database(tmp_path)
    db.claim_scan(scan_run("run-1"), now_utc=NOW)

    assert not db.commit_scan(
        "run-1",
        owner_id="worker-1",
        completed_at_utc=NOW + timedelta(minutes=5),
        now_utc=NOW + timedelta(minutes=16),
    )
    assert db.fetch_one("scan_runs", scan_run_id="run-1").status == "ACTIVE"


def test_transaction_commit_rejects_naive_timestamps_at_its_boundary(tmp_path):
    db = migrated_database(tmp_path)
    db.claim_scan(scan_run("run-1"), now_utc=NOW)

    with db.scan_transaction() as tx:
        with pytest.raises(ValueError, match="completed_at_utc must be timezone-aware"):
            tx.commit_scan(
                "run-1",
                owner_id="worker-1",
                completed_at_utc=datetime(2026, 7, 18, 0, 2),
                now_utc=NOW + timedelta(minutes=2),
            )
        with pytest.raises(ValueError, match="now_utc must be timezone-aware"):
            tx.commit_scan(
                "run-1",
                owner_id="worker-1",
                completed_at_utc=NOW + timedelta(minutes=2),
                now_utc=datetime(2026, 7, 18, 0, 2),
            )


def test_option_snapshot_correction_is_append_only_and_links_to_original(tmp_path):
    db = migrated_database(tmp_path)

    with db.scan_transaction() as tx:
        assert tx.insert_option_snapshot(option_snapshot("snapshot-1"))
        assert tx.insert_option_snapshot(
            option_snapshot(
                "snapshot-2",
                supersedes_id="snapshot-1",
                bid=1.02,
                captured_at_utc=NOW + timedelta(minutes=1),
            )
        )

    assert db.count("option_snapshots") == 2
    correction = db.fetch_one("option_snapshots", option_snapshot_id="snapshot-2")
    assert correction.supersedes_id == "snapshot-1"


def test_option_liquidity_correction_is_append_only_and_links_to_original(tmp_path):
    db = migrated_database(tmp_path)

    with db.scan_transaction() as tx:
        assert tx.insert_option_liquidity_daily(option_liquidity("liquidity-1"))
        assert tx.insert_option_liquidity_daily(
            option_liquidity(
                "liquidity-2",
                supersedes_id="liquidity-1",
                total_option_volume=12_750,
                observed_at_utc=NOW + timedelta(minutes=1),
            )
        )

    assert db.count("option_liquidity_daily") == 2
    correction = db.fetch_one("option_liquidity_daily", liquidity_id="liquidity-2")
    assert correction.supersedes_id == "liquidity-1"


def test_concurrent_claim_has_one_owner_and_classifies_duckdb_contention(
    tmp_path, monkeypatch
):
    db = migrated_database(tmp_path)
    rendezvous = Barrier(2)
    original_insert = FFTransaction.insert_scan_run

    def synchronized_insert(
        transaction: FFTransaction, record: dict[str, object]
    ) -> bool:
        rendezvous.wait(timeout=10)
        return original_insert(transaction, record)

    monkeypatch.setattr(FFTransaction, "insert_scan_run", synchronized_insert)

    def claim(run_id: str, owner_id: str) -> tuple[str, str]:
        try:
            claimed = db.claim_scan(
                scan_run(run_id, owner_id=owner_id),
                now_utc=NOW,
            )
        except (duckdb.TransactionException, duckdb.ConstraintException) as error:
            return "write_contention", type(error).__name__
        except ActiveScanError as error:
            return "claim_conflict", type(error).__name__
        return "claimed", claimed

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda pair: claim(*pair),
                (("run-1", "worker-1"), ("run-2", "worker-2")),
            )
        )

    assert [status for status, _ in outcomes].count("claimed") == 1
    assert {status for status, _ in outcomes} <= {
        "claimed",
        "write_contention",
        "claim_conflict",
    }
    assert db.count("scan_runs") == 1


def test_duckdb_connections_and_queried_timestamps_use_utc(tmp_path):
    db = migrated_database(tmp_path)
    eastern = timezone(timedelta(hours=-4))
    db.claim_scan(
        scan_run("run-1", claimed_at_utc=NOW.astimezone(eastern)),
        now_utc=NOW,
    )

    queried = db.fetch_one("scan_runs", scan_run_id="run-1").claimed_at_utc

    assert db.session_timezone() == "UTC"
    assert queried.utcoffset() == timedelta(0)
    assert queried.isoformat().endswith("+00:00")
