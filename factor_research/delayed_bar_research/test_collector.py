"""Synthetic tests run without local historical caches or legacy modules."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SPEC = importlib.util.spec_from_file_location("delayed_collector", Path(__file__).with_name("collector.py"))
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def bars(days=3):
    import exchange_calendars as xc
    cal = xc.get_calendar("XNYS", start="2024-10-01", end="2024-11-30")
    rows = []
    for day in cal.sessions_in_range("2024-10-01", "2024-11-29")[:days]:
        for ts in pd.date_range(cal.session_open(day) + pd.Timedelta(minutes=5), cal.session_close(day), freq="5min"):
            c = 100 * np.exp(len(rows) * 0.0001)
            rows.append(dict(timestamp=ts, session_date=ts.tz_convert("America/New_York").strftime("%Y-%m-%d"),
                             open=c-0.01, high=c+0.02, low=c-0.02, close=c,
                             corporate_action_regime_id="R0", bar_available_at=None,
                             timestamp_semantics="RTH_5M_BAR_END"))
    return pd.DataFrame(rows)


def test_mf038_is_numeric_with_exact_prior20_and_clip():
    refs = [dict(rv=0.01, opening_range=2., id=str(i)) for i in range(20)]
    assert collector.predict("MF038", 3., 0, refs)["prediction"] == pytest.approx(0.015)
    assert collector.predict("MF038", 100., 0, refs)["prediction"] == pytest.approx(0.02)
    assert collector.predict("MF038", 0.1, 0, refs)["prediction"] == pytest.approx(0.005)
    assert collector.predict("MF038", 3., 0, refs[:19]) is None


def test_mf043_reference_window_counts_sessions_and_not_valid_members():
    refs = [dict(ret=0.001, id=str(i)) for i in range(60)]
    result = collector.predict("MF043", 0., -1, refs)
    assert result["baseline"] == pytest.approx(0.001)
    assert result["prediction"] == -1
    assert collector.predict("MF043", 0., 1, refs[:39]) is None
    # Old valid members outside the 60-session window cannot fill recent gaps.
    assert collector.predict("MF043", 0., 1, refs + [dict(ret=None, id="gap")] * 21) is None


def test_ols_atr_and_rearm_preserve_frozen_definition():
    frame = bars(1)
    signal = collector.signals(frame)
    assert signal.side.iloc[:23].eq(0).all()
    assert signal.side.iloc[23] == 1
    assert signal.side.iloc[24:].eq(0).all()
    assert signal.r_squared.iloc[-1] == pytest.approx(1.)
    assert signal.atr20.iloc[-1] == pytest.approx(0.04)
    assert collector.rearm([1, 1, -1, -1, 0, -1, 1]) == [1, 0, -1, 0, 0, -1, 1]


@pytest.mark.parametrize("factor", ["MF038", "MF043"])
def test_future_mutations_do_not_change_anchor_prediction(factor):
    frame = bars(3)
    anchor = 2*78 + (5 if factor == "MF038" else 30)
    original = collector.signals(frame).iloc[anchor]
    changed = frame.copy()
    changed.loc[anchor+1:, ["open", "high", "low", "close"]] *= 10
    mutated = collector.signals(changed).iloc[anchor]
    prefix = collector.signals(frame.iloc[:anchor+1]).iloc[-1]
    for col in ["opening_range", "side", "q", "r_squared", "atr20", "regime_ok"]:
        assert original[col] == pytest.approx(mutated[col], nan_ok=True)
        assert original[col] == pytest.approx(prefix[col], nan_ok=True)


def test_target_excludes_buffer_and_uses_six_complete_bars():
    frame = bars(1)
    target = collector.target(frame, 5, 6)
    assert target["first_label"] == "10:10"
    assert target["last_label"] == "10:35"
    changed = frame.copy()
    changed.loc[6, ["open", "high", "low", "close"]] *= 9  # 10:05 buffer end
    assert collector.target(changed, 5, 6) == target
    outcome = frame.iloc[7:13]
    legs = np.r_[np.log(outcome.close.iloc[0]/outcome.open.iloc[0]), np.diff(np.log(outcome.close))]
    assert target["rv"] == pytest.approx(np.sqrt(np.sum(legs**2)))
    assert target["ret"] == pytest.approx(np.log(outcome.close.iloc[-1]/outcome.open.iloc[0]))
    assert collector.target(frame, 72, 6) is None


@pytest.mark.parametrize("defect", ["duplicate", "order", "price", "gap", "forming", "date", "regime", "availability"])
def test_validation_fails_closed(defect):
    frame = bars(1)
    if defect == "duplicate": frame.loc[1, "timestamp"] = frame.loc[0, "timestamp"]
    if defect == "order": frame = frame.iloc[::-1]
    if defect == "price": frame.loc[1, "low"] = -1
    if defect == "gap": frame = frame.drop(index=3)
    if defect == "forming": frame.loc[1, "timestamp_semantics"] = "IN_PROGRESS"
    if defect == "date": frame.loc[1, "session_date"] = "2024-10-02"
    if defect == "regime": frame.loc[1, "corporate_action_regime_id"] = "R1"
    if defect == "availability": frame.loc[1, "bar_available_at"] = "2024-10-01T14:00:00Z"
    with pytest.raises(ValueError): collector.validate(frame)


def test_calendar_covers_dst_early_close_and_rejects_whole_session_gap():
    frame = bars(43)
    clean = collector.validate(frame)
    assert clean.timestamp.dt.tz_convert("America/New_York").map(lambda x:x.utcoffset()).nunique() == 2
    assert clean.groupby("session_date").size().min() == 42
    day = clean.session_date.unique()[3]
    with pytest.raises(ValueError, match="SESSION_GRID"):
        collector.validate(clean.loc[clean.session_date.ne(day)])


def test_csv_roundtrip_accepts_exact_grid_across_datetime_precision_units():
    from io import StringIO
    original = bars(2)
    reread = pd.read_csv(StringIO(original.to_csv(index=False)))
    reread["timestamp"] = pd.to_datetime(reread.timestamp, utc=True).dt.as_unit("us")
    clean = collector.validate(reread)
    assert clean.timestamp.tolist() == original.timestamp.tolist()
    # A real off-grid nanosecond must still be rejected after precision normalization.
    shifted = original.copy()
    shifted.loc[4, "timestamp"] += pd.Timedelta(nanoseconds=1)
    with pytest.raises(ValueError, match="SESSION_GRID"):
        collector.validate(shifted)


def test_valid_single_session_does_not_require_a_cached_calendar():
    assert len(collector.validate(bars(1))) == 78


def test_regime_crossing_disables_factor_lookback():
    frame = bars(2)
    frame.loc[78:, "corporate_action_regime_id"] = "R1"
    signal = collector.signals(frame)
    assert not signal.regime_ok.iloc[78:101].any()
    assert signal.regime_ok.iloc[101]


def test_session_inference_does_not_weight_busy_sessions_more():
    events = pd.DataFrame([dict(session_date="2020-01-02", score=1.)]*9 + [dict(session_date="2020-01-03", score=3.)])
    result = collector.summarize(events, "MF043", draws=20, flips=40)
    assert result["mean_session_score"] == 2.
    assert result["event_count"] == 10
    assert result["session_count"] == 2
    assert 0 < result["raw_p"] <= 1
    assert collector.holm([0.01, 1.]) == [0.02, 1.]


def test_empty_sample_is_not_a_positive_result():
    result = collector.summarize(pd.DataFrame(columns=["session_date", "score"]), "MF038", draws=10, flips=10)
    assert result["p_for_holm"] == 1.
    assert result["mean_session_score"] is None


def test_journal_fsync_receipt_and_immutable_attempt(tmp_path):
    run = tmp_path / "attempt"
    collector.reserve(run)
    with pytest.raises(FileExistsError): collector.reserve(run)
    receipt = collector.seal(run / "PREDICTIONS.jsonl", [{"anchor_at": "2024-10-01T14:00:00Z"}])
    assert receipt["clock_status"] == "UNVERIFIED"
    assert receipt["fsync_completed_monotonic_ns"] >= receipt["started_monotonic_ns"]
    assert receipt["fsync_completed_at_utc"]
    assert json.loads((run / "PREDICTIONS.jsonl").read_text())["anchor_at"] == "2024-10-01T14:00:00Z"


def test_manifest_verification_detects_revision_and_path_escape(tmp_path):
    payload = tmp_path/"data.csv"
    payload.write_text("raw")
    entry = {"path": "data.csv", "sha256": collector.sha(payload), "size_bytes": 3}
    collector.verify_entries(tmp_path, [entry])
    payload.write_text("revised")
    with pytest.raises(ValueError, match="IDENTITY"):
        collector.verify_entries(tmp_path, [entry])
    with pytest.raises(ValueError, match="PATH"):
        collector.verify_entries(tmp_path, [dict(entry, path="../outside")])


def test_cli_cannot_start_live_or_clock_experiment():
    with pytest.raises(SystemExit): collector.main(["live"])
    contract = json.loads(Path(__file__).with_name("RESEARCH_CONTRACT.json").read_text())
    assert contract["mode"] == "HISTORICAL_REPLAY_ONLY"
    assert not contract["evidence"]["confirmatory_use_allowed"]
    assert collector.sha(Path(__file__).with_name("RESEARCH_CONTRACT.json")) == collector.CONTRACT_SHA256


def test_replay_seals_each_session_before_accessing_its_outcomes(tmp_path, monkeypatch):
    frame = collector.validate(bars(43))
    original_target = collector.target
    original_seal = collector.seal
    sealed = set()

    def observed_seal(path, records):
        result = original_seal(path, records)
        if path.name == "DURABLE_RECEIPTS.jsonl":
            sealed.add(records[0]["session_date"])
        return result

    def observed_target(day, offset, horizon):
        assert day.session_date.iloc[0] in sealed
        return original_target(day, offset, horizon)

    monkeypatch.setattr(collector, "seal", observed_seal)
    monkeypatch.setattr(collector, "target", observed_target)
    events, _ = collector.replay(frame, pd.DataFrame(columns=["ex_date"]), "RAW", tmp_path, "synthetic")
    primary = events.loc[events.factor.eq("MF038") & events.horizon.eq(6)]
    assert len(primary) == 22  # First session lacks 20 bars, then exact-20 reference warmup.
    predictions = [json.loads(line) for line in (tmp_path/"PREDICTIONS.jsonl").read_text().splitlines()]
    for prediction in predictions:
        assert all(pd.Timestamp(r["target_end_at"]) < pd.Timestamp(prediction["anchor_at"])
                   for r in prediction["references"])
        assert prediction["deadline_status"] == "NOT_PROVEN"
        assert prediction["actual_data_available_at_utc"] is None


def test_parity_compares_only_audit_raw_events():
    # The frozen audit stored RAW event rows only; adjusted sensitivity is separate.
    rows = [dict(factor=f, horizon=6, session_date="2020-01-02", anchor_at="2020-01-02T15:00:00Z",
                 price_basis=b, score=1., factor_value=1., baseline_error=2., forecast_error=1.)
            for f in collector.FACTORS for b in ["RAW", "RETROSPECTIVE_ADJUSTED"]]
    events = pd.DataFrame(rows)
    metrics = {f: collector.summarize(events.loc[events.factor.eq(f) & events.price_basis.eq("RAW")], f, draws=20, flips=40)
               for f in collector.FACTORS}
    expected = pd.DataFrame([dict(m, master_factor_id=f) for f, m in metrics.items()])
    audit = events.loc[events.price_basis.eq("RAW")].rename(columns={"factor":"master_factor_id", "anchor_at":"timestamp"})
    assert all(collector.parity(events, metrics, expected, audit).values())
