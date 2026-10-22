"""All inputs, clocks and transports in this suite are Synthetic."""
import ast
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location("a2_collector", HERE / "collector.py")
c = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c)


class Clock:
    def __init__(self, at="2027-01-04T15:01:00Z"):
        self.at = pd.Timestamp(at)
        self.ns = 0
        self.qualified = True

    def sample(self):
        self.ns += 1_000_000
        return dict(utc=self.at.isoformat(), monotonic_ns=self.ns,
                    uncertainty_seconds=0., qualified=self.qualified,
                    evidence_class="SYNTHETIC")


def bars(start="2027-01-04", days=1):
    cal = c.calendar()
    rows = []
    for day in cal.sessions_in_range(start, "2027-12-31")[:days]:
        for ts in c.grid(str(day.date())):
            close = 100 * np.exp(len(rows)*.0001)
            rows.append(dict(timestamp=ts.isoformat(), session_date=str(day.date()),
                             open=close-.01, high=close+.02, low=close-.02, close=close,
                             regime="R0", completed=True,
                             completion_basis="SYNTHETIC_COMPLETED_BAR",
                             completed_at=ts.isoformat(), version="v1"))
    return rows


def payload(rows):
    return dict(source_kind="SYNTHETIC", timestamp_semantics="RTH_5M_BAR_END",
                bars=rows, corporate_actions=[], corporate_action_pit=True,
                actions_coverage_through="2027-12-31")


def prepared(tmp_path, factor="MF038", horizon=6, days=43):
    rows = bars(days=days)
    days = list(dict.fromkeys(r["session_date"] for r in rows))
    day = days[-1]
    clock = Clock((pd.Timestamp(rows[0]["timestamp"])+pd.Timedelta(seconds=1)).isoformat())
    run = c.Collector(tmp_path / "run", clock)
    # Warmup labels were observed and sealed on preceding sessions only.
    for d in days[:-1]:
        daily = [r for r in rows if r["session_date"] == d]
        clock.at = pd.Timestamp(daily[-1]["timestamp"])+pd.Timedelta(seconds=1)
        run.ingest(payload(daily))
        for h in (6,):
            for ts in c.grid(d):
                if ts + pd.Timedelta(minutes=5*(h+1)) <= c.calendar().session_close(d):
                    # Only anchors needed by assertions, including MF043 11:30.
                    if ts.tz_convert("America/New_York").strftime("%H:%M") in {"09:35", "10:00"}:
                        run.mature_reference(ts.isoformat(), h)
    anchor = c.calendar().session_open(day)+pd.Timedelta(minutes=30 if factor == "MF038" else 5)
    clock.at = anchor+pd.Timedelta(seconds=1)
    current = [r for r in rows if r["session_date"] == day and pd.Timestamp(r["timestamp"]) <= anchor]
    run.ingest(payload(current))
    return run, clock, rows, anchor


def test_copied_math_is_frozen_and_matches_accepted_baseline():
    assert c.verify_math_identity()
    old = HERE.parent / "delayed_bar_research" / "collector.py"
    if old.exists():
        tree = ast.parse(old.read_text(encoding="utf-8"))
        funcs = {n.name: ast.dump(n, include_attributes=False) for n in tree.body if isinstance(n, ast.FunctionDef)}
        new = ast.parse((HERE/"collector.py").read_text(encoding="utf-8"))
        for n in new.body:
            if isinstance(n, ast.FunctionDef) and n.name in c.MATH_FUNCTIONS:
                assert ast.dump(n, include_attributes=False) == funcs[n.name]


def test_exact_reference_math():
    refs = [dict(rv=.01, opening_range=2., ret=.001, id=str(i)) for i in range(60)]
    assert c.predict("MF038", 100., 0, refs)["prediction"] == pytest.approx(.02)
    assert c.predict("MF038", 3., 0, refs[:19]) is None
    assert c.predict("MF043", 0., -1, refs)["prediction"] == -1
    assert c.predict("MF043", 0., 1, refs+[dict(ret=None,id="gap")]*21) is None
    assert c.rearm([1,1,-1,-1,0,-1,1]) == [1,0,-1,0,0,-1,1]


def test_prefix_and_future_perturbations():
    frame = pd.DataFrame(bars(days=3)).rename(columns={"regime":"corporate_action_regime_id"})
    anchor = 2*78+5
    full = c.signals(frame).iloc[anchor]
    changed = frame.copy()
    changed.loc[anchor+1:,["open","high","low","close"]] *= 10
    for other in (c.signals(changed).iloc[anchor],c.signals(frame.iloc[:anchor+1]).iloc[-1]):
        for col in ("opening_range","side","q","r_squared","atr20","regime_ok"):
            assert full[col] == pytest.approx(other[col],nan_ok=True)


def test_pre_freeze_session_and_live_source_are_rejected_and_preserved(tmp_path):
    run = c.Collector(tmp_path/"run",Clock())
    for bad in (dict(payload(bars()),source_kind="OPEND"),payload([dict(bars()[0],session_date="2020-01-02",timestamp="2020-01-02T14:35:00Z")])):
        with pytest.raises(ValueError): run.ingest(bad)
    kinds = [e["kind"] for e in run.journal.events()]
    assert kinds.count("RAW") == 2
    assert kinds.count("FAILURE") == 2


@pytest.mark.parametrize("defect",["forming","missing_proof","future","negative","naive","off_grid","duplicate"])
def test_raw_defects_fail_closed(tmp_path,defect):
    clock=Clock("2027-01-04T22:00:00Z")
    run=c.Collector(tmp_path/"run",clock)
    rows=bars()[:6]
    if defect=="forming": rows[1]["completed"]=False
    if defect=="missing_proof": rows[1]["completion_basis"]=None
    if defect=="future": rows[1]["completed_at"]="2028-01-01T00:00:00Z"
    if defect=="negative": rows[1]["low"]=-1
    if defect=="naive": rows[1]["timestamp"]="2027-01-04T09:40:00"
    if defect=="off_grid": rows[1]["timestamp"]="2027-01-04T14:40:00.000000001Z"
    if defect=="duplicate": rows.append(rows[1])
    with pytest.raises(ValueError): run.ingest(payload(rows))
    assert run.journal.events()[-1]["kind"]=="FAILURE"


def test_seal_then_fetch_label_and_future_changes_cannot_rewrite_prediction(tmp_path):
    run,clock,rows,anchor=prepared(tmp_path)
    pid=run.predict_event("MF038",anchor.isoformat())
    before=(run.path/"EVENTS.jsonl").read_bytes()
    prediction=run.prediction(pid)
    assert len(prediction["references"])==20
    assert not prediction["prospective_eligible"]
    with pytest.raises(ValueError,match="TARGET_NOT_MATURE"):
        run.collect_label(pid,lambda:pytest.fail("early fetch"))
    clock.at=anchor+pd.Timedelta(minutes=35,seconds=1)
    seen=[]
    def fetch():
        events=run.journal.events()
        assert events[-1]["kind"]=="LABEL_REQUEST"
        assert any(e["kind"]=="PREDICTION_READY" for e in events)
        seen.append(True)
        target_rows=[dict(r) for r in rows if anchor<pd.Timestamp(r["timestamp"])<=anchor+pd.Timedelta(minutes=35)]
        for r in target_rows:  # Includes mutated buffer and target prices.
            for k in ("open","high","low","close"): r[k]*=2
        return payload(target_rows)
    label=run.collect_label(pid,fetch)
    assert seen and label["prediction_id"]==pid
    assert (run.path/"EVENTS.jsonl").read_bytes().startswith(before)
    assert run.prediction(pid)==prediction
    assert label["simulation_temporal_eligible"]
    assert not label["prospective_eligible"]
    assert label["first_target_bar_end"]== (anchor+pd.Timedelta(minutes=10)).isoformat()
    assert label["last_target_bar_end"]== (anchor+pd.Timedelta(minutes=35)).isoformat()
    run.finish()
    assert c.verify_bundle(run.path)["status"]=="SYNTHETIC_ENGINEERING_ONLY"


def test_late_seal_cannot_fetch_or_claim_forward(tmp_path):
    run,clock,_,anchor=prepared(tmp_path)
    clock.at=anchor+pd.Timedelta(hours=8)
    with pytest.raises(ValueError,match="DEADLINE"):
        run.predict_event("MF038",anchor.isoformat())
    assert run.journal.events()[-1]["payload"]["reason"]=="DEADLINE_NOT_PROVEN"


def test_unqualified_clock_and_missing_input_are_failures(tmp_path):
    run,clock,_,anchor=prepared(tmp_path)
    clock.qualified=False
    with pytest.raises(ValueError,match="CLOCK"):
        run.predict_event("MF038",anchor.isoformat())
    other=c.Collector(tmp_path/"other",Clock())
    rows=bars()[:6]
    other.ingest(payload(rows[:2]+rows[3:]))
    with pytest.raises(ValueError,match="GRID"):
        other.predict_event("MF038",rows[-1]["timestamp"])


def test_exact_mf043_window_keeps_missing_sessions(tmp_path):
    run,clock,_,anchor=prepared(tmp_path)
    refs=run.references("MF043",anchor,6,"R0")
    assert len(refs)==42
    assert sum(r.get("ret") is not None for r in refs)==42
    run.refs.pop((refs[-1]["session_date"],"10:00",6,"R0"))
    refs=run.references("MF043",pd.Timestamp(anchor),6,"R0")
    assert len(refs)==42 and sum(r.get("ret") is not None for r in refs)==41


def test_revisions_invalidate_without_overwriting(tmp_path):
    run,clock,rows,anchor=prepared(tmp_path)
    pid=run.predict_event("MF038",anchor.isoformat())
    original=run.prediction(pid)
    revised=dict(next(r for r in rows if pd.Timestamp(r["timestamp"])==anchor))
    revised["version"]="v2"
    with pytest.raises(ValueError,match="REVISION"):
        run.ingest(payload([revised]))
    assert run.prediction(pid)==original
    assert pid in run.invalid_predictions
    clock.at=anchor+pd.Timedelta(minutes=36)
    with pytest.raises(ValueError,match="INVALIDATED"):
        run.collect_label(pid,lambda:pytest.fail("invalidated fetch"))


def test_tamper_and_consumed_attempt(tmp_path):
    run=c.Collector(tmp_path/"run",Clock())
    run.finish()
    with pytest.raises(FileExistsError): c.Collector(run.path,Clock())
    path=run.path/"EVENTS.jsonl"
    path.write_bytes(path.read_bytes().replace(b"ENGINEERING",b"FAKE"))
    with pytest.raises(ValueError): c.verify_bundle(run.path)


def test_calendar_dst_early_close_and_buffer():
    assert len(c.grid("2027-11-26"))==42
    assert c.grid("2027-03-12")[0].hour==14
    assert c.grid("2027-03-15")[0].hour==13
    frame=pd.DataFrame(bars()).rename(columns={"regime":"corporate_action_regime_id"})
    before=c.target(frame,5,6)
    frame.loc[6,["open","high","low","close"]]*=99
    assert c.target(frame,5,6)==before
    assert c.target(frame,72,6) is None


def test_cli_and_contract_have_no_live_scoring_or_scheduler_entry():
    contract=c.load_contract()
    assert not contract["authorization"]["real_opend"]
    assert not contract["authorization"]["phase4"]
    for command in ("live","replay","schedule","score"):
        with pytest.raises(SystemExit): c.main([command])


def test_mf043_actual_event_uses_prior60_and_original_target(tmp_path):
    run,clock,rows,anchor=prepared(tmp_path,factor="MF043")
    pid=run.predict_event("MF043",anchor.isoformat())
    pred=run.prediction(pid)
    assert pred["prediction"]==1 and len(pred["references"])==42
    assert all(pd.Timestamp(r["target_end_at"]) < anchor for r in pred["references"])
    clock.at=anchor+pd.Timedelta(minutes=36)
    target_rows=[r for r in rows if anchor<pd.Timestamp(r["timestamp"])<=anchor+pd.Timedelta(minutes=35)]
    label=run.collect_label(pid,lambda:payload(target_rows))
    assert label["score"]==pytest.approx((label["ret"]-pred["baseline"])*10000)
    assert not label["prospective_eligible"]


def test_mf043_old_valid_members_cannot_replace_recent_missing_sessions(tmp_path):
    run,_,_,anchor=prepared(tmp_path,days=65)
    refs=run.references("MF043",anchor,6,"R0")
    assert len(refs)==60
    assert len(run.refs)>60
    for ref in refs[-21:]:
        del run.refs[(ref["session_date"],"10:00",6,"R0")]
    refs=run.references("MF043",anchor,6,"R0")
    assert len(refs)==60
    assert sum(r.get("ret") is not None for r in refs)==39
    assert c.predict("MF043",0.,1,refs) is None


def test_prediction_fsync_crossing_deadline_preserves_prediction_but_rejects_label(tmp_path,monkeypatch):
    run,clock,_,anchor=prepared(tmp_path)
    original=run.journal._write
    def slow_write(name,record):
        original(name,record)
        if record.get("kind")=="PREDICTION_READY":
            clock.at=anchor+pd.Timedelta(minutes=5)
    monkeypatch.setattr(run.journal,"_write",slow_write)
    with pytest.raises(ValueError,match="FSYNC_LATE"):
        run.predict_event("MF038",anchor.isoformat())
    assert len(run.predictions)==1
    pid=next(iter(run.predictions))
    clock.at=anchor+pd.Timedelta(minutes=36)
    with pytest.raises(ValueError,match="FSYNC_LATE"):
        run.collect_label(pid,lambda:pytest.fail("late prediction must not fetch"))


def test_fetch_failure_is_recorded_redacted_and_cannot_be_retried(tmp_path):
    run,clock,_,anchor=prepared(tmp_path)
    pid=run.predict_event("MF038",anchor.isoformat())
    clock.at=anchor+pd.Timedelta(minutes=36)
    def fail(): raise ConnectionError("sensitive simulated diagnostic")
    with pytest.raises(ValueError,match="LABEL_FETCH_FAILED"): run.collect_label(pid,fail)
    assert "sensitive simulated diagnostic" not in (run.path/"EVENTS.jsonl").read_text()
    with pytest.raises(ValueError,match="CONSUMED"):
        run.collect_label(pid,lambda:pytest.fail("no retry"))


def test_partial_receipt_fails_closed_and_existing_attempt_cannot_resume(tmp_path,monkeypatch):
    run=c.Collector(tmp_path/"run",Clock())
    original=run.journal._write
    def crash(name,record):
        if name=="RECEIPTS.jsonl": raise OSError("synthetic disk failure")
        original(name,record)
    monkeypatch.setattr(run.journal,"_write",crash)
    with pytest.raises(OSError): run.ingest(payload(bars()[:1]))
    with pytest.raises(ValueError,match="INCOMPLETE"): run.journal.verify()
    with pytest.raises(FileExistsError): c.Collector(run.path,Clock())


@pytest.mark.parametrize("defect",["missing_target","revised_reference","changed_actions"])
def test_post_seal_defects_keep_failures_and_never_qualify(tmp_path,defect):
    run,clock,rows,anchor=prepared(tmp_path)
    pid=run.predict_event("MF038",anchor.isoformat())
    clock.at=anchor+pd.Timedelta(minutes=36)
    if defect=="missing_target":
        outcome=[r for r in rows if anchor<pd.Timestamp(r["timestamp"])<=anchor+pd.Timedelta(minutes=35)][:-1]
        with pytest.raises(ValueError,match="GRID"): run.collect_label(pid,lambda:payload(outcome))
    elif defect=="revised_reference":
        ref=run.prediction(pid)["references"][-1]
        bar_id=ref["input_ids"][-1]
        row=dict(next(r for r in run.rows.values() if r["id"]==bar_id))
        for k in ("id","raw_commit","observed_clock"): row.pop(k)
        row["version"]="v2"
        with pytest.raises(ValueError,match="REVISION"): run.ingest(payload([row]))
        assert pid in run.invalid_predictions
    else:
        data=payload([])
        data["corporate_actions"]=[run.prediction(pid)["session_date"]]
        with pytest.raises(ValueError,match="REVISION"): run.ingest(data)
        assert pid in run.invalid_predictions
        assert not run.refs
    assert run.journal.events()[-1]["kind"]=="FAILURE"
    assert not run.prediction(pid)["prospective_eligible"]


def test_raw_nan_and_order_failures_are_preserved(tmp_path):
    run=c.Collector(tmp_path/"run",Clock("2027-01-04T22:00:00Z"))
    rows=bars()[:6]
    rows[0]["close"]=float("nan")
    with pytest.raises(ValueError): run.ingest(payload(rows))
    assert "NaN" in run.journal.events()[-2]["payload"]["response_json"]
    with pytest.raises(ValueError,match="ORDER"): run.ingest(payload(bars()[:6][::-1]))


def test_company_action_blackout_and_regime_reset(tmp_path):
    run=c.Collector(tmp_path/"run",Clock("2027-01-06T22:00:00Z"))
    data=payload(bars(days=3))
    data["corporate_actions"]=["2027-01-05"]
    with pytest.raises(ValueError,match="REGIME_NOT_CHANGED"): run.ingest(data)
    assert not run.rows
    for row in data["bars"]:
        if row["session_date"] >= "2027-01-05": row["regime"]="R1"
    run.ingest(data)
    assert all(run._blackout(d) for d in ("2027-01-04","2027-01-05","2027-01-06"))
    frame=pd.DataFrame(data["bars"]).rename(columns={"regime":"corporate_action_regime_id"})
    signal=c.signals(frame)
    assert not signal.regime_ok.iloc[78:101].any()
    assert signal.regime_ok.iloc[101]


def test_target_revision_after_label_invalidates_qualified_count(tmp_path):
    run,clock,rows,anchor=prepared(tmp_path)
    pid=run.predict_event("MF038",anchor.isoformat())
    clock.at=anchor+pd.Timedelta(minutes=36)
    outcome=[r for r in rows if anchor<pd.Timestamp(r["timestamp"])<=anchor+pd.Timedelta(minutes=35)]
    label=run.collect_label(pid,lambda:payload(outcome))
    revised=dict(outcome[-1],version="v2")
    with pytest.raises(ValueError,match="REVISION"): run.ingest(payload([revised]))
    assert pid in run.invalid_predictions
    assert label["simulation_temporal_eligible"]  # Immutable historical statement.
    result=run.finish()["verified_evidence"]
    assert result["label_count"]==1
    assert result["invalidated_count"]==1
    assert result["simulation_eligible_label_count"]==0


def test_late_first_fsync_then_utc_rollback_never_qualifies(tmp_path,monkeypatch):
    run,clock,_,anchor=prepared(tmp_path)
    original=run.journal._write
    def rollback(name,record):
        original(name,record)
        if record.get("kind")=="PREDICTION": clock.at=anchor+pd.Timedelta(minutes=6)
        if name=="RECEIPTS.jsonl" and len(run.predictions)==0 and clock.at>anchor+pd.Timedelta(minutes=5):
            clock.at=anchor+pd.Timedelta(minutes=1)
    monkeypatch.setattr(run.journal,"_write",rollback)
    with pytest.raises(ValueError,match="FSYNC_LATE"): run.predict_event("MF038",anchor.isoformat())
    assert run.journal.clock_fault
    pid=next(iter(run.predictions))
    clock.at=anchor+pd.Timedelta(minutes=36)
    with pytest.raises(ValueError,match="FSYNC_LATE"):
        run.collect_label(pid,lambda:pytest.fail("UTC rollback cannot qualify"))


def test_hash_consistent_orphan_label_is_rejected_by_semantic_audit(tmp_path):
    run=c.Collector(tmp_path/"run",Clock())
    run.journal.append("LABEL",dict(prediction_id="orphan",label_id="fake"))
    run.journal.verify()  # Structurally valid chains alone are insufficient.
    with pytest.raises(ValueError,match="AUDIT_LABEL_IDENTITY"): run.finish()


def test_hash_consistent_wrong_commit_is_rejected(tmp_path):
    run=c.Collector(tmp_path/"run",Clock())
    commit=run.journal.append("FAILURE",dict(reason="SYNTHETIC",prospective_eligible=False))
    run.journal.append("PREDICTION_READY",dict(prediction_id="fake",prediction_commit=commit))
    run.journal.verify()
    with pytest.raises(ValueError,match="AUDIT_COMMIT_LINK"): run.finish()


def test_malformed_revision_response_is_rejected_without_corrupting_original_identity(tmp_path):
    run,clock,rows,anchor=prepared(tmp_path)
    pid=run.predict_event("MF038",anchor.isoformat())
    bad=dict(next(r for r in rows if pd.Timestamp(r["timestamp"])==anchor),low=-1)
    with pytest.raises(ValueError,match="INVALID_OHLC"): run.ingest(payload([bad]))
    assert pid not in run.invalid_predictions
    assert run.finish()["verified_evidence"]["invalidated_count"]==0


@pytest.mark.parametrize("stage",["LABEL_REQUEST","RAW","LABEL"])
def test_clock_loss_during_label_processing_fails_closed(tmp_path,monkeypatch,stage):
    run,clock,rows,anchor=prepared(tmp_path)
    pid=run.predict_event("MF038",anchor.isoformat())
    clock.at=anchor+pd.Timedelta(minutes=36)
    original=run.journal._write
    def lose_clock(name,record):
        original(name,record)
        if record.get("kind")==stage: clock.qualified=False
    monkeypatch.setattr(run.journal,"_write",lose_clock)
    calls=[]
    def fetch():
        calls.append(True)
        return payload([r for r in rows if anchor<pd.Timestamp(r["timestamp"])<=anchor+pd.Timedelta(minutes=35)])
    with pytest.raises(ValueError,match="CLOCK_UNQUALIFIED"): run.collect_label(pid,fetch)
    assert bool(calls)==(stage!="LABEL_REQUEST")
    assert run.finish()["verified_evidence"]["simulation_eligible_label_count"]==0


def test_same_kind_wrong_reference_receipt_is_rejected(tmp_path):
    run,clock,_,anchor=prepared(tmp_path)
    refs=run.references("MF038",anchor,6,"R0")
    refs[-1]["commit"]=refs[-2]["commit"]
    run.predict_event("MF038",anchor.isoformat())
    # Mutable in-memory corruption is caught independently from the hash chain.
    with pytest.raises(ValueError,match="AUDIT_REFERENCE_RECEIPT_LINK"): run.finish()


def test_revision_returned_by_label_source_preserves_verifiable_failure_bundle(tmp_path):
    run,clock,rows,anchor=prepared(tmp_path)
    pid=run.predict_event("MF038",anchor.isoformat())
    clock.at=anchor+pd.Timedelta(minutes=36)
    revised=dict(next(r for r in rows if pd.Timestamp(r["timestamp"])==anchor),version="v2")
    with pytest.raises(ValueError,match="BAR_REVISION"):
        run.collect_label(pid,lambda:payload([revised]))
    evidence=run.finish()["verified_evidence"]
    assert evidence["invalidated_count"]==1
    assert evidence["label_count"]==0
