"""A2 Synthetic engineering collector. No OpenD, trading, replay or scheduling entry.

Synthetic clocks and completion certificates never establish real PIT/Forward status.
The copied mathematical kernels below are AST-bound to accepted Attempt 02.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import platform
import time
import uuid

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
MATH_FUNCTIONS = ("rearm", "signals", "predict", "target")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def value_sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def utc(value):
    result = pd.Timestamp(value)
    require(result.tzinfo is not None, "NAIVE_TIMESTAMP")
    return result.tz_convert("UTC")


@lru_cache(maxsize=1)
def calendar():
    import exchange_calendars as xc
    return xc.get_calendar("XNYS", start="2020-01-01", end="2035-12-31")


@lru_cache(maxsize=1024)
def grid(day):
    cal = calendar()
    return pd.date_range(cal.session_open(day)+pd.Timedelta(minutes=5), cal.session_close(day), freq="5min")


def load_contract():
    import importlib.metadata as metadata
    contract = json.loads((HERE/"RESEARCH_CONTRACT.json").read_text(encoding="utf-8"))
    require(contract["mode"] == "SYNTHETIC_ENGINEERING_ONLY", "CONTRACT_MODE")
    require(contract["status"] == "ENGINEERING_FROZEN", "CONTRACT_NOT_FROZEN")
    require(not any(contract["authorization"].values()), "REAL_EXECUTION_NOT_AUTHORIZED")
    require(contract["code_sha256"] == file_sha(__file__), "CODE_IDENTITY_DRIFT")
    require(all(metadata.version(p)==v for p,v in contract["runtime_versions"].items()),"RUNTIME_VERSION_DRIFT")
    return contract


def verify_math_identity():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    actual = {n.name: hashlib.sha256(ast.dump(n, include_attributes=False).encode()).hexdigest()
              for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in MATH_FUNCTIONS}
    require(actual == load_contract()["math_ast_sha256"], "FROZEN_MATH_DRIFT")
    return True


def rearm(values):
    armed = {1: True, -1: True}
    emitted = []
    for value in values:
        emitted.append(value if value and armed[value] else 0)
        if value:
            armed[value] = False
        else:
            armed = {1: True, -1: True}
    return emitted

def signals(frame):
    """Only causal features; no target/label table is accepted by this API."""
    f = frame.copy().reset_index(drop=True)
    f["timestamp"] = pd.to_datetime(f.timestamp, utc=True)
    f["clock"] = f.timestamp.dt.tz_convert("America/New_York").dt.strftime("%H:%M")
    grouped = f.groupby("session_date", sort=False)
    f["opening_range"] = grouped.high.cummax() - grouped.low.cummin()
    previous = f.close.shift(1)
    tr = pd.concat([f.high-f.low, (f.high-previous).abs(), (f.low-previous).abs()], axis=1).max(axis=1)
    first = grouped.cumcount().eq(0)
    tr.loc[first] = (f.high-f.low).loc[first]
    f["atr20"] = tr.rolling(20, min_periods=20).mean()
    x = np.arange(24, dtype=float)

    def slope(v):
        return float(np.polyfit(x, v, 1)[0])

    def r2(v):
        total = float(np.sum((v-v.mean())**2))
        return np.nan if total == 0 else float(1-np.sum((v-np.polyval(np.polyfit(x, v, 1), x))**2)/total)

    rolling = np.log(f.close).rolling(24, min_periods=24)
    b = rolling.apply(slope, raw=True)
    f["r_squared"] = rolling.apply(r2, raw=True)
    f["q"] = (24*b).abs() / (f.atr20/f.close).replace(0, np.nan) * f.r_squared
    raw = pd.Series(np.where((f.q >= .5) & (f.r_squared >= .6), np.sign(b), 0), index=f.index).fillna(0).astype(int)
    f["side"] = 0
    for positions in grouped.indices.values():
        f.loc[positions, "side"] = rearm(raw.iloc[positions].tolist())
    codes = pd.Series(pd.factorize(f.corporate_action_regime_id, sort=False)[0])
    f["regime_ok"] = codes.rolling(24, min_periods=24).max().eq(codes.rolling(24, min_periods=24).min())
    f["mf038_regime_ok"] = codes.rolling(20, min_periods=20).max().eq(codes.rolling(20, min_periods=20).min())
    return f

def predict(factor, opening_range, side, references):
    if factor == "MF038":
        refs = [r for r in references if r.get("rv") is not None and r.get("opening_range") is not None][-20:]
        if len(refs) != 20 or not np.isfinite(opening_range):
            return None
        baseline = float(np.median([r["rv"] for r in refs]))
        scale = float(np.median([r["opening_range"] for r in refs]))
        if scale <= 0:
            return None
        prediction = baseline * float(np.clip(opening_range/scale, .5, 2.))
    elif factor == "MF043":
        refs = [r for r in references[-60:] if r.get("ret") is not None]
        if len(refs) < 40 or side not in {-1, 1}:
            return None
        baseline = float(np.median([r["ret"] for r in refs]))
        prediction = int(side)
    else:
        raise ValueError("UNREGISTERED_FACTOR")
    return {"prediction": prediction, "baseline": baseline, "reference_ids": [r["id"] for r in refs],
            "references": refs}

def target(day, offset, horizon):
    first, last = offset+2, offset+horizon+1
    if last >= len(day):
        return None
    outcome = day.iloc[first:last+1]
    if outcome.corporate_action_regime_id.nunique() != 1 or outcome.corporate_action_regime_id.iloc[0] != day.corporate_action_regime_id.iloc[offset]:
        return None
    closes = outcome.close.to_numpy(dtype=float)
    legs = np.r_[np.log(closes[0]/float(outcome.open.iloc[0])), np.log(closes[1:]/closes[:-1])]
    return {"ret": float(np.log(closes[-1]/float(outcome.open.iloc[0]))),
            "rv": float(np.sqrt(np.sum(legs**2))), "first_label": pd.Timestamp(outcome.timestamp.iloc[0]).tz_convert("America/New_York").strftime("%H:%M"),
            "last_label": pd.Timestamp(outcome.timestamp.iloc[-1]).tz_convert("America/New_York").strftime("%H:%M")}


def _read_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _check_chain(records):
    previous = None
    for seq, record in enumerate(records):
        body = {k:v for k,v in record.items() if k != "sha256"}
        require(record["seq"] == seq and record["previous"] == previous and
                value_sha(body) == record["sha256"], "JOURNAL_IDENTITY_DRIFT")
        previous = record["sha256"]


class Journal:
    """Two fsynced chains; a partial append is an unrecoverable consumed attempt."""
    def __init__(self, path, clock, process_id):
        self.path, self.clock, self.process_id = path, clock, process_id
        self.count = 0
        self.previous_event = self.previous_receipt = None
        self.last_commit_ns = -1
        self.last_utc = None
        self.clock_fault = False

    def sample(self):
        sample = self.clock.sample()
        at = utc(sample["utc"])
        self.clock_fault |= bool(self.last_utc is not None and at < self.last_utc)
        self.last_utc = at if self.last_utc is None else max(at,self.last_utc)
        # Sticky qualification loss prevents a later apparently good sample from
        # laundering an earlier bad or reversed clock observation.
        self.clock_fault |= not (sample["qualified"] is True and sample["evidence_class"]=="SYNTHETIC"
                                 and np.isfinite(sample["uncertainty_seconds"])
                                 and 0 <= sample["uncertainty_seconds"] <= 1.)
        return dict(sample,timeline_qualified=not self.clock_fault)

    def events(self):
        path = self.path/"EVENTS.jsonl"
        return _read_lines(path) if path.exists() else []

    def verify(self):
        events = self.events()
        receipt_path = self.path/"RECEIPTS.jsonl"
        receipts = _read_lines(receipt_path) if receipt_path.exists() else []
        _check_chain(events)
        _check_chain(receipts)
        require(len(events) == len(receipts) == self.count, "INCOMPLETE_DURABLE_RECEIPT")
        previous = -1
        for event, receipt in zip(events, receipts):
            require(receipt["event_sha256"] == event["sha256"] and
                    event["process_id"] == self.process_id and
                    receipt["process_id"] == self.process_id and
                    previous < receipt["started_monotonic_ns"] <= receipt["event_fsync_monotonic_ns"],
                    "DURABLE_ORDER_NOT_PROVEN")
            previous = receipt["event_fsync_monotonic_ns"]
        return events

    def append(self, kind, payload):
        self.verify()
        start = self.sample()
        require(start["monotonic_ns"] > self.last_commit_ns,"MONOTONIC_REVERSED")
        event = dict(seq=self.count, previous=self.previous_event, kind=kind,
                     payload=json.loads(canonical(payload)), process_id=self.process_id)
        event["sha256"] = value_sha(event)
        self._write("EVENTS.jsonl", event)
        done = self.sample()
        require(start["monotonic_ns"] <= done["monotonic_ns"], "MONOTONIC_REVERSED")
        receipt = dict(seq=self.count, previous=self.previous_receipt, event_sha256=event["sha256"],
                       process_id=self.process_id, started_monotonic_ns=start["monotonic_ns"],
                       event_fsync_monotonic_ns=done["monotonic_ns"], started_clock=start,event_fsync_clock=done)
        receipt["sha256"] = value_sha(receipt)
        self._write("RECEIPTS.jsonl", receipt)
        commit = dict(event_sha256=event["sha256"], receipt_sha256=receipt["sha256"],
                      receipt_fsync_clock=self.sample(), process_id=self.process_id)
        require(commit["receipt_fsync_clock"]["monotonic_ns"] >= done["monotonic_ns"],"MONOTONIC_REVERSED")
        self.count += 1
        self.previous_event, self.previous_receipt = event["sha256"], receipt["sha256"]
        self.last_commit_ns = commit["receipt_fsync_clock"]["monotonic_ns"]
        return commit

    def _write(self, name, record):
        with (self.path/name).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical(record)+"\n")
            handle.flush()
            os.fsync(handle.fileno())


class Collector:
    """Injected Synthetic transport only; existing attempts cannot be resumed."""
    def __init__(self, path, clock):
        self.contract = load_contract()
        verify_math_identity()
        self.path, self.clock = Path(path), clock
        self.path.mkdir(parents=True, exist_ok=False)
        self.process_id = str(uuid.uuid4())
        self.journal = Journal(self.path, clock, self.process_id)
        self.rows, self.refs, self.predictions, self.ready, self.label_dependencies = {}, {}, {}, {}, {}
        self.bad_bars, self.invalid_predictions, self.attempts, self.labels = set(), set(), set(), set()
        self.actions, self.action_identity = None, None
        self.action_invalid = False
        self.closed = False
        import importlib.metadata as metadata
        self.journal.append("ATTEMPT", dict(mode="SYNTHETIC_ENGINEERING_ONLY", consumed=True,
                            retry_allowed=False, contract=self.contract,
                            contract_sha256=file_sha(HERE/"RESEARCH_CONTRACT.json"), code_sha256=file_sha(__file__),
                            python=platform.python_version(), dependencies={p:metadata.version(p)
                            for p in ("numpy","pandas","exchange-calendars","tzdata")},
                            process_id=self.process_id, phase4_started=False, prospective_eligible=False))

    def reject(self, reason, **context):
        self.journal.append("FAILURE", dict(reason=reason, context=context, prospective_eligible=False))
        raise ValueError(reason)

    def check_open(self):
        require(not self.closed, "ATTEMPT_CLOSED")
        self.journal.verify()
        require(file_sha(HERE/"RESEARCH_CONTRACT.json") == self.journal.events()[0]["payload"]["contract_sha256"]
                and file_sha(__file__) == self.journal.events()[0]["payload"]["code_sha256"], "RUNTIME_IDENTITY_DRIFT")

    def ingest(self, payload):
        self.check_open()
        now = self.journal.sample()
        raw_json = json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=True)
        raw = self.journal.append("RAW", dict(response_json=raw_json,
                    response_sha256=hashlib.sha256(raw_json.encode()).hexdigest(),observed_clock=now))
        try:
            require(payload["source_kind"] == "SYNTHETIC", "REAL_OPEND_NOT_AUTHORIZED")
            require(payload["timestamp_semantics"] == "RTH_5M_BAR_END", "BAR_TIME_SEMANTICS")
            require(payload["corporate_action_pit"] is True, "CORPORATE_ACTION_PIT_UNKNOWN")
            action = {k:payload[k] for k in ("corporate_actions","actions_coverage_through")}
            for day in action["corporate_actions"]:
                require(calendar().is_session(day), "INVALID_EX_DATE")
            staged = {}
            prior_ts = None
            for original in payload["bars"]:
                row = json.loads(canonical(original))
                ts, completion = utc(row["timestamp"]), utc(row["completed_at"])
                day = row["session_date"]
                require(ts.tz_convert("America/New_York").strftime("%Y-%m-%d") == day, "SESSION_DATE")
                require(calendar().session_open(day) > utc(self.contract["frozen_at_utc"]), "PRE_FREEZE_SESSION")
                require(ts in grid(day), "OFF_GRID_BAR")
                require(row["completed"] is True and row["completion_basis"] == "SYNTHETIC_COMPLETED_BAR" and
                        ts <= completion <= utc(now["utc"]), "BAR_COMPLETION_NOT_PROVEN")
                prices = [row[k] for k in ("open","high","low","close")]
                require(all(np.isfinite(v) and v > 0 for v in prices) and
                        row["low"] <= min(row["open"],row["close"]) <= max(row["open"],row["close"]) <= row["high"], "INVALID_OHLC")
                require(isinstance(row["regime"],str) and row["regime"].strip() and row["version"], "MISSING_VERSION_OR_REGIME")
                key, bar_id = ts.isoformat(), value_sha(row)
                require(key not in staged, "DUPLICATE_BAR")
                require(prior_ts is None or ts > prior_ts,"RAW_TIME_ORDER")
                prior_ts = ts
                if key in self.rows and self.rows[key]["id"] != bar_id:
                    self.bad_bars.add(key)
                    self._invalidate(self.rows[key]["id"], "BAR_REVISION")
                    raise ValueError("BAR_REVISION")
                staged[key] = dict(row, id=bar_id, raw_commit=raw, observed_clock=now)
            if self.actions and self.actions["corporate_actions"] != action["corporate_actions"]:
                self.action_invalid = True
                self.refs.clear()
                for pid in self.predictions:
                    self.invalid_predictions.add(pid)
                    self.journal.append("INVALIDATION",dict(prediction_id=pid,reason="CORPORATE_ACTION_REVISION"))
                raise ValueError("CORPORATE_ACTION_REVISION")
            combined = dict(self.rows, **staged)
            for ex in action["corporate_actions"]:
                previous_day = str(calendar().previous_session(ex).date())
                before = [r["regime"] for r in combined.values() if r["session_date"]==previous_day]
                after = [r["regime"] for r in combined.values() if r["session_date"]==ex]
                require(not before or not after or before[-1] != after[0],"EX_DATE_REGIME_NOT_CHANGED")
            self.actions, self.action_identity = action, value_sha(action)
            self.journal.append("RAW_ADMITTED",dict(raw_commit=raw,bar_ids=[r["id"] for r in staged.values()],
                                                   action=action,action_identity=self.action_identity))
            for key,row in staged.items():
                if key not in self.rows: self.rows[key]=row
        except (ValueError, KeyError, TypeError) as error:
            self.reject(str(error), raw_event=raw["event_sha256"])
        return raw

    def _invalidate(self, bar_id, reason):
        for pid, pred in self.predictions.items():
            reference_inputs = {i for ref in pred["references"] for i in ref.get("input_ids",[])}
            if bar_id in set(pred["input_ids"]) | reference_inputs | self.label_dependencies.get(pid,set()):
                self.invalid_predictions.add(pid)
                self.journal.append("INVALIDATION", dict(prediction_id=pid, reason=reason, bar_id=bar_id))
        for key, ref in list(self.refs.items()):
            if bar_id in ref["input_ids"]: del self.refs[key]

    def _prefix(self, anchor):
        anchor = utc(anchor)
        rows = [r for key,r in sorted(self.rows.items()) if utc(key) <= anchor]
        require(rows, "INPUT_GRID_EMPTY")
        days = calendar().sessions_in_range(rows[0]["session_date"], anchor.tz_convert("America/New_York").date().isoformat())
        expected = [ts for day in days for ts in grid(str(day.date())) if ts <= anchor]
        actual = [utc(r["timestamp"]) for r in rows]
        require(actual == expected and actual[-1] == anchor, "INPUT_GRID_MISSING")
        require(not any(ts.isoformat() in self.bad_bars for ts in actual), "INPUT_REVISION_QUARANTINED")
        frame = pd.DataFrame(rows).rename(columns={"regime":"corporate_action_regime_id"})
        for _, group in frame.groupby("session_date"):
            require(group.corporate_action_regime_id.nunique() == 1, "INTRADAY_REGIME_CHANGE")
        return frame

    def _blackout(self, day):
        require(not self.action_invalid,"CORPORATE_ACTION_REVISION_QUARANTINED")
        require(self.actions is not None, "MISSING_CORPORATE_ACTION_SNAPSHOT")
        next_day = str(calendar().next_session(day).date())
        require(self.actions["actions_coverage_through"] >= next_day, "CORPORATE_ACTION_COVERAGE")
        blocked = set()
        for ex in self.actions["corporate_actions"]:
            blocked.update((ex,str(calendar().previous_session(ex).date()),str(calendar().next_session(ex).date())))
        return day in blocked

    def mature_reference(self, anchor, horizon=6):
        self.check_open()
        try:
            anchor = utc(anchor)
            require(horizon in (3,6,12), "UNREGISTERED_HORIZON")
            end = anchor+pd.Timedelta(minutes=5*(horizon+1))
            require(end <= utc(self.journal.sample()["utc"]), "REFERENCE_NOT_MATURE")
            frame = self._prefix(end)
            prefix = frame.loc[pd.to_datetime(frame.timestamp,utc=True) <= anchor]
            day = anchor.tz_convert("America/New_York").strftime("%Y-%m-%d")
            local = frame.loc[frame.session_date.eq(day)].reset_index(drop=True)
            positions = local.index[pd.to_datetime(local.timestamp,utc=True).eq(anchor)]
            require(len(positions)==1, "REFERENCE_ANCHOR")
            result = target(local,int(positions[0]),horizon)
            require(result is not None, "REFERENCE_WINDOW")
            current = prefix.loc[prefix.session_date.eq(day)]
            regime = current.corporate_action_regime_id.iloc[-1]
            same20 = len(prefix)>=20 and prefix.corporate_action_regime_id.iloc[-20:].eq(regime).all()
            blackout = self._blackout(day)
            # OR/regime lookback plus target OHLC; no unrelated older/future bar
            # identities may change a frozen reference's mathematical content.
            dependencies = pd.concat([prefix.loc[prefix.session_date.eq(day)],prefix.iloc[-20:],
                                       local.iloc[int(positions[0])+2:int(positions[0])+horizon+2]])
            ref = dict(result,session_date=day,clock=anchor.tz_convert("America/New_York").strftime("%H:%M"),
                       regime=regime,horizon=horizon,anchor_at=anchor.isoformat(),target_end_at=end.isoformat(),
                       opening_range=float(current.high.max()-current.low.min()),
                       mf038_qualified=bool(same20 and not blackout),
                       input_ids=dependencies.id.drop_duplicates().tolist(),action_identity=self.action_identity)
            ref["id"] = value_sha(ref)
            key = (day,ref["clock"],horizon,regime)
            require(key not in self.refs, "REFERENCE_ALREADY_SEALED")
            ref["commit"] = self.journal.append("REFERENCE",ref)
            self.refs[key]=ref
            return ref["id"]
        except (ValueError,KeyError) as error:
            self.reject(str(error),anchor=str(anchor))

    def references(self, factor, anchor, horizon, regime):
        anchor = utc(anchor)
        day, clock = anchor.tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M").split()
        first = min((r["session_date"] for r in self.rows.values()),default=day)
        days = [str(d.date()) for d in calendar().sessions_in_range(first,day) if str(d.date()) < day]
        if factor=="MF043": days=days[-60:]
        refs=[]
        for d in days:
            ref=self.refs.get((d,clock,horizon,regime))
            if ref and utc(ref["target_end_at"]) < anchor:
                require(ref["id"]==value_sha({k:v for k,v in ref.items() if k not in {"id","commit"}}),"REFERENCE_IDENTITY_DRIFT")
                if factor=="MF038" and not ref["mf038_qualified"]: continue
                refs.append(ref)
            elif factor=="MF043":
                refs.append(dict(id=value_sha([d,clock,horizon,regime,"MISSING"]),session_date=d,ret=None))
        return refs[-20:] if factor=="MF038" else refs

    def _time_qualified(self, sample):
        return (sample["evidence_class"]=="SYNTHETIC" and sample["qualified"] is True and
                sample.get("timeline_qualified") is True and not self.journal.clock_fault and
                0 <= sample["uncertainty_seconds"] <= self.contract["clock_uncertainty_max_seconds"])

    def predict_event(self, factor, anchor, horizon=6):
        self.check_open()
        anchor=utc(anchor)
        key=(factor,anchor.isoformat(),horizon)
        try:
            require(key not in self.attempts,"SIGNAL_ATTEMPT_CONSUMED")
            self.attempts.add(key)
            require(factor in ("MF038","MF043") and horizon in (3,6,12),"UNREGISTERED_SIGNAL")
            now=self.journal.sample()
            require(self._time_qualified(now),"CLOCK_UNQUALIFIED")
            deadline=anchor+pd.Timedelta(minutes=5)
            require(utc(now["utc"])+pd.Timedelta(seconds=now["uncertainty_seconds"]) < deadline,"DEADLINE_NOT_PROVEN")
            require(utc(now["utc"])-pd.Timedelta(seconds=now["uncertainty_seconds"]) >= anchor,"ANCHOR_NOT_COMPLETED")
            frame=self._prefix(anchor)
            require(all(utc(sample["utc"]) <= utc(now["utc"]) for sample in frame.observed_clock),"OBSERVATION_CLOCK_REVERSED")
            sig=signals(frame)
            row=sig.iloc[-1]
            day=row.session_date
            require(not self._blackout(day),"CORPORATE_ACTION_BLACKOUT")
            require(anchor+pd.Timedelta(minutes=5*(horizon+1)) <= calendar().session_close(day),"TARGET_OUTSIDE_SESSION")
            require((row.clock=="10:00" and row.mf038_regime_ok) if factor=="MF038" else (row.side!=0 and row.regime_ok),"NO_QUALIFIED_SIGNAL")
            refs=self.references(factor,anchor,horizon,row.corporate_action_regime_id)
            result=predict(factor,float(row.opening_range),int(row.side),refs)
            require(result is not None,"REFERENCE_WARMUP")
            first=frame.index[frame.session_date.eq(day)][0]
            start=max(0,min(first,len(frame)-20)) if factor=="MF038" else max(0,first-23)
            input_ids=frame.id.iloc[start:].tolist()
            pred=dict(result,factor=factor,horizon=horizon,anchor_at=anchor.isoformat(),session_date=day,
                      deadline_at=deadline.isoformat(),target_start_at=deadline.isoformat(),
                      target_end_at=(anchor+pd.Timedelta(minutes=5*(horizon+1))).isoformat(),
                      regime=row.corporate_action_regime_id,input_ids=input_ids,
                      action_identity=self.action_identity,contract_sha256=file_sha(HERE/"RESEARCH_CONTRACT.json"),
                      evidence_class="SYNTHETIC_ENGINEERING_ONLY",prospective_eligible=False)
            pid=value_sha(pred)
            commit=self.journal.append("PREDICTION",dict(prediction_id=pid,prediction=pred))
            # Both fsync stages must be timely; READY cannot rehabilitate a late
            # prediction commit, even if UTC subsequently moves backwards.
            first_seal=commit["receipt_fsync_clock"]
            first_timely=(self._time_qualified(first_seal) and
                          utc(first_seal["utc"])+pd.Timedelta(seconds=first_seal["uncertainty_seconds"]) < deadline)
            ready=self.journal.append("PREDICTION_READY",dict(prediction_id=pid,prediction_commit=commit))
            self.predictions[pid]=json.loads(canonical(pred))
            self.ready[pid]=ready
            sealed=ready["receipt_fsync_clock"]
            require(first_timely and self._time_qualified(sealed) and
                    utc(sealed["utc"])+pd.Timedelta(seconds=sealed["uncertainty_seconds"]) < deadline,
                    "PREDICTION_FSYNC_LATE")
            return pid
        except (ValueError,KeyError) as error:
            self.reject(str(error),factor=factor,anchor=anchor.isoformat(),horizon=horizon)

    def prediction(self, prediction_id):
        return json.loads(canonical(self.predictions[prediction_id]))

    def collect_label(self, prediction_id, fetch):
        self.check_open()
        try:
            require(prediction_id in self.ready,"PREDICTION_NOT_SEALED")
            require(prediction_id not in self.labels,"LABEL_ATTEMPT_CONSUMED")
            require(prediction_id not in self.invalid_predictions,"PREDICTION_INVALIDATED")
            pred=self.prediction(prediction_id)
            ready=self.ready[prediction_id]
            sealed=ready["receipt_fsync_clock"]
            require(self._time_qualified(sealed) and
                    utc(sealed["utc"])+pd.Timedelta(seconds=sealed["uncertainty_seconds"]) < utc(pred["target_start_at"]),
                    "PREDICTION_FSYNC_LATE")
            now=self.journal.sample()
            require(self._time_qualified(now),"CLOCK_UNQUALIFIED")
            require(utc(now["utc"])-pd.Timedelta(seconds=now["uncertainty_seconds"]) >= utc(pred["target_end_at"]),"TARGET_NOT_MATURE")
            self.labels.add(prediction_id)
            request=self.journal.append("LABEL_REQUEST",dict(prediction_id=prediction_id,prediction_ready_commit=ready))
            require(self._time_qualified(request["receipt_fsync_clock"]),"CLOCK_UNQUALIFIED_LABEL_REQUEST")
            try:
                response=fetch()
            except Exception as error:
                self.reject("LABEL_FETCH_FAILED",error_type=type(error).__name__)
            self.ingest(response)
            require(self._time_qualified(self.journal.sample()),"CLOCK_UNQUALIFIED_LABEL_INPUT")
            require(prediction_id not in self.invalid_predictions,"PREDICTION_INVALIDATED")
            frame=self._prefix(pred["target_end_at"])
            day=frame.loc[frame.session_date.eq(pred["session_date"])].reset_index(drop=True)
            offset=int(day.index[pd.to_datetime(day.timestamp,utc=True).eq(utc(pred["anchor_at"]))][0])
            result=target(day,offset,pred["horizon"])
            require(result is not None,"TARGET_WINDOW_INCOMPLETE")
            target_rows=day.iloc[offset+2:offset+pred["horizon"]+2]
            ready_seq=next(e["seq"] for e in self.journal.events() if e["sha256"]==ready["event_sha256"])
            for commit in target_rows.raw_commit:
                seq=next(e["seq"] for e in self.journal.events() if e["sha256"]==commit["event_sha256"])
                require(seq>ready_seq,"LABEL_DATA_PREKNOWN")
            score=(abs(result["rv"]-pred["baseline"])-abs(result["rv"]-pred["prediction"])) if pred["factor"]=="MF038" else pred["prediction"]*(result["ret"]-pred["baseline"])*10000
            label=dict(result,prediction_id=prediction_id,score=score,target_input_ids=target_rows.id.tolist(),
                       first_target_bar_end=utc(target_rows.timestamp.iloc[0]).isoformat(),
                       last_target_bar_end=utc(target_rows.timestamp.iloc[-1]).isoformat(),
                       prediction_ready_commit=ready,simulation_temporal_eligible=True,
                       prospective_eligible=False,evidence_class="SYNTHETIC_ENGINEERING_ONLY")
            label["label_id"]=value_sha(label)
            commit=self.journal.append("LABEL",label)
            self.journal.append("LABEL_DURABLE",dict(label_id=label["label_id"],label_commit=commit))
            self.label_dependencies[prediction_id]=set(label["target_input_ids"])
            if self.journal.clock_fault:
                self.invalid_predictions.add(prediction_id)
                self.journal.append("INVALIDATION",dict(prediction_id=prediction_id,reason="CLOCK_UNQUALIFIED_LABEL_FSYNC"))
                self.reject("CLOCK_UNQUALIFIED_LABEL_FSYNC",prediction_id=prediction_id)
            return label
        except (ValueError,KeyError,TypeError) as error:
            self.reject(str(error),prediction_id=prediction_id)

    def finish(self):
        self.check_open()
        commit=self.journal.append("END",dict(status="SYNTHETIC_ENGINEERING_ONLY",prospective_eligible=False,
                          prediction_count=len(self.predictions),label_attempt_count=len(self.labels),
                          invalidated_count=len(self.invalid_predictions),phase4_started=False))
        manifest=dict(status="SYNTHETIC_ENGINEERING_ONLY",process_id=self.process_id,
                      last_commit=commit,files=[dict(path=name,sha256=file_sha(self.path/name),
                      size_bytes=(self.path/name).stat().st_size) for name in ("EVENTS.jsonl","RECEIPTS.jsonl")])
        with (self.path/"MANIFEST.json").open("x",encoding="utf-8",newline="\n") as handle:
            handle.write(canonical(manifest)+"\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.closed=True
        return verify_bundle(self.path)


def verify_bundle(path):
    path=Path(path).resolve()
    manifest=json.loads((path/"MANIFEST.json").read_text(encoding="utf-8"))
    require({e["path"] for e in manifest["files"]}=={"EVENTS.jsonl","RECEIPTS.jsonl"},"MANIFEST_FILES")
    for entry in manifest["files"]:
        file=path/entry["path"]
        require(file.is_file() and file_sha(file)==entry["sha256"] and file.stat().st_size==entry["size_bytes"],"MANIFEST_IDENTITY")
    journal=Journal(path,None,manifest["process_id"])
    journal.count=len(_read_lines(path/"EVENTS.jsonl"))
    events=journal.verify()
    require(events[0]["kind"]=="ATTEMPT" and events[-1]["kind"]=="END" and
            events[-1]["sha256"]==manifest["last_commit"]["event_sha256"],"ATTEMPT_BOUNDARY")
    summary=verify_evidence(events,_read_lines(path/"RECEIPTS.jsonl"),manifest["last_commit"])
    require(events[-1]["payload"]["prediction_count"]==summary["prediction_count"] and
            events[-1]["payload"]["label_attempt_count"]==summary["label_attempt_count"] and
            events[-1]["payload"]["invalidated_count"]==summary["invalidated_count"],"SUMMARY_COUNTS")
    manifest["verified_evidence"]=summary
    return manifest


def verify_evidence(events, receipts, last_commit):
    """Read-only semantic verification, independent of Collector's memory state."""
    by_sha={e["sha256"]:e for e in events}
    receipt_by_event={r["event_sha256"]:r for r in receipts}
    process_id=events[0]["process_id"]
    contract=events[0]["payload"]["contract"]
    require(contract["mode"]=="SYNTHETIC_ENGINEERING_ONLY" and not any(contract["authorization"].values()),"AUDIT_AUTHORIZATION")
    if contract["code_sha256"]:
        require(contract["code_sha256"]==events[0]["payload"]["code_sha256"],"AUDIT_SOURCE_IDENTITY")

    def qualified(sample):
        return (sample["qualified"] is True and sample["evidence_class"]=="SYNTHETIC" and
                sample.get("timeline_qualified") is True and
                0 <= sample["uncertainty_seconds"] <= contract["clock_uncertainty_max_seconds"])

    def upper(sample):
        return utc(sample["utc"])+pd.Timedelta(seconds=sample["uncertainty_seconds"])

    def lower(sample):
        return utc(sample["utc"])-pd.Timedelta(seconds=sample["uncertainty_seconds"])

    def linked(commit, before, kind):
        event=by_sha.get(commit["event_sha256"])
        require(event is not None and event["kind"]==kind and event["seq"]<before and
                commit["process_id"]==process_id,"AUDIT_COMMIT_LINK")
        receipt=receipt_by_event[event["sha256"]]
        done=commit["receipt_fsync_clock"]
        require(commit["receipt_sha256"]==receipt["sha256"] and
                done["monotonic_ns"]>=receipt["event_fsync_monotonic_ns"],"AUDIT_COMMIT_RECEIPT")
        if event["seq"]+1<len(receipts):
            require(done["monotonic_ns"]<receipts[event["seq"]+1]["started_monotonic_ns"],"AUDIT_COMMIT_ORDER")
        return event

    bars,raws,refs,predictions,ready,requests,labels,dependencies,invalid={}, {}, {}, {}, {}, {}, {}, {}, set()
    required_invalid=set()
    request_qualified={}
    declared_invalid={e["payload"]["prediction_id"] for e in events if e["kind"]=="INVALIDATION"}
    action_ids=set()
    clock_lost=False
    previous_utc=None
    for event,receipt in zip(events,receipts):
        for sample in (receipt["started_clock"],receipt["event_fsync_clock"]):
            at=utc(sample["utc"])
            if previous_utc is not None and at<previous_utc: clock_lost=True
            if not qualified(sample): clock_lost=True
            require(not clock_lost or not sample.get("timeline_qualified"),"AUDIT_CLOCK_ROLLBACK")
            previous_utc=at if previous_utc is None else max(previous_utc,at)
        kind,payload,seq=event["kind"],event["payload"],event["seq"]
        if kind=="RAW":
            raw_json=payload["response_json"]
            require(hashlib.sha256(raw_json.encode()).hexdigest()==payload["response_sha256"],"AUDIT_RAW_IDENTITY")
            raws[event["sha256"]]=(json.loads(raw_json),payload["observed_clock"])
        elif kind=="RAW_ADMITTED":
            raw_event=linked(payload["raw_commit"],seq,"RAW")
            response,observed=raws[raw_event["sha256"]]
            require(response["source_kind"]=="SYNTHETIC" and response["corporate_action_pit"] is True and
                    response["timestamp_semantics"]=="RTH_5M_BAR_END","AUDIT_RAW_ADMISSION")
            action={k:response[k] for k in ("corporate_actions","actions_coverage_through")}
            require(action==payload["action"] and value_sha(action)==payload["action_identity"],"AUDIT_ACTION_IDENTITY")
            action_ids.add(payload["action_identity"])
            require([value_sha(r) for r in response["bars"]]==payload["bar_ids"],"AUDIT_BAR_IDENTITIES")
            for row in response["bars"]:
                ts=utc(row["timestamp"])
                day=row["session_date"]
                require(calendar().session_open(day)>utc(contract["frozen_at_utc"]) and ts in grid(day) and
                        day==ts.tz_convert("America/New_York").strftime("%Y-%m-%d") and
                        row["completed"] is True and row["completion_basis"]=="SYNTHETIC_COMPLETED_BAR" and
                        ts<=utc(row["completed_at"])<=utc(observed["utc"]),"AUDIT_BAR_COMPLETION")
                prices=[row[k] for k in ("open","high","low","close")]
                require(all(np.isfinite(p) and p>0 for p in prices) and
                        row["low"]<=min(row["open"],row["close"])<=max(row["open"],row["close"])<=row["high"],"AUDIT_OHLC")
                bars.setdefault(value_sha(row),(row,raw_event["seq"],observed))
        elif kind=="REFERENCE":
            require(payload["id"]==value_sha({k:v for k,v in payload.items() if k!="id"}) and
                    payload["action_identity"] in action_ids and all(i in bars for i in payload["input_ids"]),"AUDIT_REFERENCE_IDENTITY")
            require(utc(payload["target_end_at"])<=lower(receipt["started_clock"]),"AUDIT_REFERENCE_MATURITY")
            refs[payload["id"]]=payload
        elif kind=="PREDICTION":
            pred,pid=payload["prediction"],payload["prediction_id"]
            require(pid==value_sha(pred) and pid not in predictions and not pred["prospective_eligible"] and
                    pred["evidence_class"]=="SYNTHETIC_ENGINEERING_ONLY","AUDIT_PREDICTION_IDENTITY")
            require(pred["action_identity"] in action_ids,"AUDIT_PREDICTION_ACTION")
            anchor=utc(pred["anchor_at"])
            require(utc(pred["target_start_at"])==anchor+pd.Timedelta(minutes=5) and
                    utc(pred["target_end_at"])==anchor+pd.Timedelta(minutes=5*(pred["horizon"]+1)),"AUDIT_TARGET_WINDOW")
            require(all(i in bars and utc(bars[i][0]["timestamp"])<=anchor and
                        utc(bars[i][2]["utc"])<=utc(receipt["started_clock"]["utc"]) for i in pred["input_ids"]),"AUDIT_INPUT_CUTOFF")
            valid_refs=[]
            for ref in pred["references"]:
                require(ref["id"] in refs and refs[ref["id"]]=={k:v for k,v in ref.items() if k!="commit"},"AUDIT_REFERENCE_LINK")
                reference_event=linked(ref["commit"],seq,"REFERENCE")
                require(reference_event["payload"]["id"]==ref["id"],"AUDIT_REFERENCE_RECEIPT_LINK")
                require(utc(ref["target_end_at"])<anchor and ref["regime"]==pred["regime"] and
                        ref["clock"]==anchor.tz_convert("America/New_York").strftime("%H:%M"),"AUDIT_REFERENCE_CUTOFF")
                valid_refs.append(ref)
            require(len(valid_refs)==20 if pred["factor"]=="MF038" else 40<=len(valid_refs)<=60,"AUDIT_REFERENCE_COUNT")
            day=anchor.tz_convert("America/New_York").strftime("%Y-%m-%d")
            prior_days=calendar().sessions_in_range((anchor-pd.Timedelta(days=120)).date().isoformat(),day)
            prior60={str(d.date()) for d in prior_days if str(d.date())<day}
            prior60=set(sorted(prior60)[-60:])
            candidates=sorted((r for r in refs.values() if r["clock"]==anchor.tz_convert("America/New_York").strftime("%H:%M") and
                               r["regime"]==pred["regime"] and r["horizon"]==pred["horizon"] and
                               utc(r["target_end_at"])<anchor and r["session_date"]<day and
                               (r["mf038_qualified"] if pred["factor"]=="MF038" else r["session_date"] in prior60)),
                              key=lambda r:r["session_date"])
            if pred["factor"]=="MF038": candidates=candidates[-20:]
            require([r["id"] for r in valid_refs]==[r["id"] for r in candidates],"AUDIT_EXACT_REFERENCE_MEMBERSHIP")
            predictions[pid]=(pred,seq)
            dependencies[pid]=set(pred["input_ids"])|{i for ref in valid_refs for i in ref["input_ids"]}
        elif kind=="PREDICTION_READY":
            linked_pred=linked(payload["prediction_commit"],seq,"PREDICTION")
            pid=payload["prediction_id"]
            require(linked_pred["payload"]["prediction_id"]==pid and pid not in ready,"AUDIT_READY_LINK")
            ready[pid]=(payload,seq,event["sha256"])
        elif kind=="LABEL_REQUEST":
            pid=payload["prediction_id"]
            require(pid in ready and pid not in requests and pid not in invalid,"AUDIT_LABEL_REQUEST")
            ready_event=linked(payload["prediction_ready_commit"],seq,"PREDICTION_READY")
            require(ready_event["sha256"]==ready[pid][2],"AUDIT_READY_RECEIPT")
            pred=predictions[pid][0]
            first=ready[pid][0]["prediction_commit"]["receipt_fsync_clock"]
            last=payload["prediction_ready_commit"]["receipt_fsync_clock"]
            request_qualified[pid]=(not clock_lost and all(qualified(s) and upper(s)<utc(pred["target_start_at"]) for s in (first,last)) and
                                    lower(receipt["started_clock"])>=utc(pred["target_end_at"]))
            requests[pid]=payload
        elif kind=="LABEL":
            pid=payload["prediction_id"]
            require(pid in requests and pid not in invalid and pid not in labels and
                    payload["label_id"]==value_sha({k:v for k,v in payload.items() if k!="label_id"}),"AUDIT_LABEL_IDENTITY")
            pred=predictions[pid][0]
            require(payload["prediction_ready_commit"]==requests[pid]["prediction_ready_commit"] and
                    not payload["prospective_eligible"] and payload["simulation_temporal_eligible"] and
                    payload["evidence_class"]=="SYNTHETIC_ENGINEERING_ONLY" and request_qualified[pid] and
                    (not clock_lost or pid in declared_invalid),"AUDIT_LABEL_QUALIFICATION")
            ids=payload["target_input_ids"]
            expected=pd.date_range(utc(pred["anchor_at"])+pd.Timedelta(minutes=10),utc(pred["target_end_at"]),freq="5min")
            require(len(ids)==pred["horizon"] and all(i in bars for i in ids) and
                    [utc(bars[i][0]["timestamp"]) for i in ids]==list(expected) and
                    all(bars[i][1]>ready[pid][1] for i in ids),"AUDIT_LABEL_INPUTS")
            target_rows=[bars[i][0] for i in ids]
            dummy=dict(target_rows[0],timestamp=pred["anchor_at"],regime=pred["regime"])
            frame=pd.DataFrame([dummy,dummy]+target_rows).rename(columns={"regime":"corporate_action_regime_id"})
            outcome=target(frame,0,pred["horizon"])
            score=(abs(outcome["rv"]-pred["baseline"])-abs(outcome["rv"]-pred["prediction"])) if pred["factor"]=="MF038" else pred["prediction"]*(outcome["ret"]-pred["baseline"])*10000
            require(all(np.isclose(payload[k],value,rtol=1e-12,atol=1e-12) for k,value in dict(ret=outcome["ret"],rv=outcome["rv"],score=score).items()),"AUDIT_LABEL_MATH")
            labels[pid]=payload
            dependencies[pid].update(ids)
        elif kind=="LABEL_DURABLE":
            label_event=linked(payload["label_commit"],seq,"LABEL")
            require(label_event["payload"]["label_id"]==payload["label_id"],"AUDIT_LABEL_RECEIPT")
        elif kind=="INVALIDATION":
            require(payload["prediction_id"] in predictions,"AUDIT_INVALIDATION_LINK")
            invalid.add(payload["prediction_id"])
            if payload.get("bar_id"):
                refs={i:r for i,r in refs.items() if payload["bar_id"] not in r["input_ids"]}
        elif kind=="FAILURE":
            require(payload["prospective_eligible"] is False,"AUDIT_FAILURE_QUALIFICATION")
            # Invalid OHLC/completion is rejected before runtime revision
            # detection. Only its recorded revision decision quarantines an
            # existing version; malformed rejected responses cannot silently
            # change the original admitted identity.
            if payload["reason"]=="BAR_REVISION" and "raw_event" in payload["context"]:
                raw_event=payload["context"]["raw_event"]
                require(raw_event in raws,"AUDIT_FAILURE_RAW_LINK")
                response=raws[raw_event][0]
                for row in response["bars"]:
                    changed_id=value_sha(row)
                    old_ids={i for i,(old,_,_) in bars.items() if utc(old["timestamp"])==utc(row["timestamp"]) and i!=changed_id}
                    if old_ids:
                        required_invalid.update(pid for pid,deps in dependencies.items() if old_ids & deps)
                        break
        else:
            require(kind in {"ATTEMPT","END"},"AUDIT_UNKNOWN_EVENT")
    linked(last_commit,len(events),"END")
    require(required_invalid <= invalid,"AUDIT_MISSING_INVALIDATION")
    durable_ids={e["payload"]["label_id"] for e in events if e["kind"]=="LABEL_DURABLE"}
    require(all(label["label_id"] in durable_ids for label in labels.values()),"AUDIT_LABEL_NOT_DURABLE")
    return dict(prediction_count=len(predictions),label_count=len(labels),label_attempt_count=len(requests),invalidated_count=len(invalid),
                simulation_eligible_label_count=sum(pid not in invalid for pid in labels),real_prospective_eligible_count=0)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest="command",required=True)
    commands.add_parser("verify-contract")
    verify=commands.add_parser("verify-bundle")
    verify.add_argument("path",type=Path)
    args=parser.parse_args(argv)
    if args.command=="verify-contract":
        verify_math_identity()
        print(canonical(dict(status="SYNTHETIC_ENGINEERING_ONLY",contract_sha256=file_sha(HERE/"RESEARCH_CONTRACT.json"),real_collection_authorized=False)))
    else:
        print(canonical(verify_bundle(args.path)))


if __name__=="__main__":
    main()
