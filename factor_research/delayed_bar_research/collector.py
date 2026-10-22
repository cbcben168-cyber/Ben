"""Standalone, cache-only MF038/MF043 replay. No OpenD or clock-service access.

Run: python -B collector.py replay --root <Futu worktree>
Tests: python -B -m pytest test_collector.py -q -p no:cacheprovider
Dependencies: numpy, pandas, exchange-calendars, tzdata; pytest for tests.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RUN_ID = "DELAYED_BAR_RESEARCH_REPLAY_2019_2024_20261022_01"
CONTRACT_SHA256 = "ddd22795d225a03a94f46fe541c963e414d0a108cf4e3c3dbc5306c90e9aff37"
FACTORS = ("MF038", "MF043")
HORIZONS = (3, 6, 12)
DATA = "factor_research/factor_batch_screen/data_materialized/PHASE2B_DATA_2018_2024_01"
OLD_RUN = "factor_research/factor_batch_screen/outputs/runs/PHASE2B_HISTORICAL_EXPLORATORY_2019_2024_20261018_01"
AUDIT = "factor_research/factor_batch_screen/outputs/audits/FINAL_GATE_AUDIT_20261018_01"


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def value_sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def reserve(path):
    Path(path).mkdir(parents=True, exist_ok=False)
    write_json(Path(path)/"ATTEMPT.json", {"consumed": True, "started_at_utc": utc_now(),
               "clock_status": "UNVERIFIED", "retry_allowed": False})


def seal(path, records):
    """Persist a batch, then return a separate receipt measured AFTER fsync."""
    start = time.monotonic_ns()
    with Path(path).open("a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(canonical(record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return {"path": Path(path).name, "record_count": len(records),
            "batch_sha256": value_sha(records), "started_monotonic_ns": start,
            "fsync_completed_monotonic_ns": time.monotonic_ns(),
            "fsync_completed_at_utc": utc_now(), "clock_status": "UNVERIFIED"}


def write_json(path, value):
    require(not Path(path).exists(), "OUTPUT_ALREADY_EXISTS")
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def verify_entries(base, entries):
    base = Path(base).resolve()
    for entry in entries:
        path = (base / entry["path"]).resolve()
        require(path.is_relative_to(base), "SOURCE_PATH_ESCAPE")
        require(path.is_file() and sha(path) == entry["sha256"], "SOURCE_IDENTITY_DRIFT:"+str(path))
        size = entry.get("size_bytes", entry.get("bytes"))
        require(size is None or path.stat().st_size == size, "SOURCE_IDENTITY_SIZE_DRIFT")


def validate(frame):
    """Historical-only admission; never fabricate arrival time or live completion."""
    import exchange_calendars as xc
    needed = {"timestamp", "session_date", "corporate_action_regime_id", "timestamp_semantics",
              "bar_available_at", "open", "high", "low", "close"}
    require(needed <= set(frame), "MISSING_FIELDS")
    f = frame.copy().reset_index(drop=True)
    # Reject timezone-naive economic times instead of silently treating them as UTC.
    require(all(pd.Timestamp(x).tzinfo is not None for x in f.timestamp), "NAIVE_TIMESTAMP")
    f["timestamp"] = pd.to_datetime(f.timestamp, utc=True, errors="raise")
    require(len(f) > 0 and f.timestamp.is_monotonic_increasing and not f.timestamp.duplicated().any(), "TIME_ORDER_OR_DUPLICATE")
    require(f.timestamp_semantics.eq("RTH_5M_BAR_END").all(), "BAR_COMPLETION_SEMANTICS")
    require(f.bar_available_at.isna().all(), "HISTORICAL_AVAILABILITY_MUST_REMAIN_UNKNOWN")
    local = f.timestamp.dt.tz_convert("America/New_York")
    require(local.dt.strftime("%Y-%m-%d").eq(f.session_date).all(), "SESSION_DATE_MISMATCH")
    f["clock"] = local.dt.strftime("%H:%M")
    prices = f[["open", "high", "low", "close"]].to_numpy(dtype=float)
    require(np.isfinite(prices).all() and (prices > 0).all(), "INVALID_PRICE")
    require((f.high >= f[["open", "close", "low"]].max(axis=1)).all() and
            (f.low <= f[["open", "close", "high"]].min(axis=1)).all(), "INVALID_OHLC")
    require(f.corporate_action_regime_id.notna().all() and f.corporate_action_regime_id.astype(str).str.strip().ne("").all(), "MISSING_REGIME")
    cal = xc.get_calendar("XNYS", start=f.session_date.min(), end=f.session_date.max())
    expected_days = cal.sessions_in_range(f.session_date.min(), f.session_date.max()).strftime("%Y-%m-%d").tolist()
    require(f.session_date.drop_duplicates().tolist() == expected_days, "SESSION_GRID")
    for day, group in f.groupby("session_date", sort=False):
        expected = pd.date_range(cal.session_open(day)+pd.Timedelta(minutes=5), cal.session_close(day), freq="5min")
        require(pd.DatetimeIndex(group.timestamp).equals(expected), "SESSION_GRID:"+day)
        require(group.corporate_action_regime_id.nunique() == 1, "INTRADAY_REGIME_CHANGE")
    return f


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


def replay(frame, actions, basis, output, source_sha):
    f = signals(frame)
    dates = f.session_date.drop_duplicates().tolist()
    blocked = set()
    for ex in actions.ex_date.astype(str):
        if ex in dates:
            i = dates.index(ex)
            blocked.update(dates[max(0, i-1):i+2])
            if i:
                require(f.loc[f.session_date.eq(dates[i-1]), "corporate_action_regime_id"].iloc[0] !=
                        f.loc[f.session_date.eq(ex), "corporate_action_regime_id"].iloc[0], "EX_DATE_REGIME_NOT_CHANGED")
    histories = defaultdict(list)
    scored, exclusions = [], defaultdict(int)
    all_bar_ids = [value_sha([source_sha, i]) for i in range(len(f))]
    for session, day in f.groupby("session_date", sort=False):
        predictions = []
        regime = day.corporate_action_regime_id.iloc[0]
        for offset, row in enumerate(day.itertuples()):
            for factor in FACTORS:
                event = row.clock == "10:00" if factor == "MF038" else row.side != 0
                if not event or session < "2019-01-01":
                    continue
                okay = row.mf038_regime_ok if factor == "MF038" else row.regime_ok
                if session in blocked or not okay:
                    exclusions[(factor, "BLACKOUT_OR_REGIME")] += 1
                    continue
                for horizon in HORIZONS:
                    # Calendar-known window fit is tested without reading any outcome prices.
                    if offset+horizon+1 >= len(day):
                        exclusions[(factor, "TARGET_OUTSIDE_SESSION_H"+str(horizon))] += 1
                        continue
                    key = (factor, row.clock, regime, horizon)
                    require(all(pd.Timestamp(r["target_end_at"]) < row.timestamp for r in histories[key]), "FUTURE_REFERENCE")
                    result = predict(factor, row.opening_range, int(row.side), histories[key])
                    if result is None:
                        exclusions[(factor, "REFERENCE_WARMUP_H"+str(horizon))] += 1
                        continue
                    n = offset+1 if factor == "MF038" else 24
                    input_ids = all_bar_ids[row.Index-n+1:row.Index+1]
                    record = dict(result, factor=factor, horizon=horizon, session_date=session,
                                  anchor_at=row.timestamp.isoformat(), deadline_at=(row.timestamp+pd.Timedelta(minutes=5)).isoformat(),
                                  factor_value=float(row.opening_range) if factor == "MF038" else int(row.side),
                                  price_basis=basis, regime=regime, input_ids=input_ids,
                                  source_sha256=source_sha, historical_bar_available_at=None,
                                  first_provably_completed_at=None, provider_publication_at=None,
                                  actual_data_available_at_utc=None, evidence_class="HISTORICAL_REPLAY",
                                  deadline_status="NOT_PROVEN", offset=offset)
                    record["prediction_id"] = value_sha(record)
                    predictions.append(record)
        # Forecasts are durably sealed before this session's labels are even calculated.
        receipt = seal(output/"PREDICTIONS.jsonl", predictions)
        receipt.update(session_date=session, price_basis=basis)
        seal(output/"DURABLE_RECEIPTS.jsonl", [receipt])
        matured = {}
        labels = []
        for offset, row in enumerate(day.itertuples()):
            for horizon in HORIZONS:
                t = target(day, offset, horizon)
                ref = dict(t or {"ret": None, "rv": None}, opening_range=float(row.opening_range),
                           anchor_at=row.timestamp.isoformat(),
                           target_end_at=(row.timestamp+pd.Timedelta(minutes=5*(horizon+1))).isoformat())
                ref["id"] = value_sha([source_sha, row.Index, horizon, t])
                matured[offset, horizon] = ref
                histories["MF043", row.clock, regime, horizon].append(ref)
                histories["MF043", row.clock, regime, horizon] = histories["MF043", row.clock, regime, horizon][-60:]
                if row.clock == "10:00" and session >= "2019-01-01" and session not in blocked and row.mf038_regime_ok and t is not None:
                    histories["MF038", row.clock, regime, horizon].append(ref)
                    histories["MF038", row.clock, regime, horizon] = histories["MF038", row.clock, regime, horizon][-20:]
        for prediction in predictions:
            t = matured[prediction["offset"], prediction["horizon"]]
            baseline, forecast = prediction["baseline"], prediction["prediction"]
            if prediction["factor"] == "MF038":
                be, fe = abs(t["rv"]-baseline), abs(t["rv"]-forecast)
                score = be-fe
            else:
                be = fe = None
                score = forecast*(t["ret"]-baseline)*10000
            label = dict(prediction_id=prediction["prediction_id"], label_id=t["id"],
                         prediction_batch_sha256=receipt["batch_sha256"],
                         factor=prediction["factor"], horizon=prediction["horizon"],
                         session_date=session, anchor_at=prediction["anchor_at"], price_basis=basis,
                         side=int(forecast) if prediction["factor"] == "MF043" else 0,
                         factor_value=prediction["factor_value"],
                         score=float(score), baseline_error=be, forecast_error=fe)
            labels.append(label)
            scored.append(label)
        seal(output/"LABELS.jsonl", labels)
    return pd.DataFrame(scored), [{"factor": k[0], "reason": k[1], "count": v, "price_basis": basis} for k, v in exclusions.items()]


def holm(values):
    values = np.asarray(values, dtype=float)
    order = np.argsort(values)
    result = np.empty(len(values))
    result[order] = np.minimum(1., np.maximum.accumulate(values[order]*(len(values)-np.arange(len(values)))))
    return result.tolist()


def summarize(events, factor, draws=2000, flips=20000):
    sessions = events.groupby("session_date", sort=True).score.mean()
    result = {"factor": factor, "event_count": len(events), "session_count": len(sessions),
              "mean_session_score": None, "median_session_score": None, "ci95_low": None,
              "ci95_high": None, "raw_p": None, "p_for_holm": 1.}
    if sessions.empty:
        return result
    values = sessions.to_numpy(dtype=float)
    ordinal = {"MF038": 37, "MF043": 42}[factor]
    rng = np.random.default_rng(20261017+ordinal)
    years = pd.to_datetime(sessions.index).year
    groups = [values[years == year] for year in sorted(set(years))]
    estimates = [np.concatenate([rng.choice(g, size=len(g), replace=True) for g in groups]).mean() for _ in range(draws)]
    rng = np.random.default_rng(20261017+1000+ordinal)
    exceed = 0
    for start in range(0, flips, 2000):
        signs = rng.choice(np.array([-1., 1.]), size=(min(2000, flips-start), len(values)))
        exceed += int((np.abs((signs*values).mean(axis=1)) >= abs(values.mean())-1e-15).sum())
    p = (exceed+1)/(flips+1)
    result.update(mean_session_score=float(values.mean()), median_session_score=float(np.median(values)),
                  ci95_low=float(np.quantile(estimates, .025)), ci95_high=float(np.quantile(estimates, .975)), raw_p=p, p_for_holm=p)
    if factor == "MF038":
        for prefix, col in [("baseline", "baseline_error"), ("factor", "forecast_error")]:
            result[prefix+"_mae"] = float(events[col].mean())
            result[prefix+"_rmse"] = float(np.sqrt(np.mean(events[col]**2)))
    return result


def stability(events):
    rows = []
    for (basis, factor, horizon), group in events.groupby(["price_basis", "factor", "horizon"], sort=True):
        s = group.groupby("session_date", sort=True).score.mean()
        years = pd.to_datetime(s.index).year
        for count, name in [(2, "HALF"), (3, "THIRD")]:
            for i, positions in enumerate(np.array_split(np.arange(len(s)), count)):
                rows.append(dict(price_basis=basis, factor=factor, horizon=int(horizon), diagnostic=name, slice=str(i+1),
                                 n=len(positions), effect=float(s.iloc[positions].mean()) if len(positions) else None))
        annual = s.groupby(years).sum()
        denominator = float(annual.abs().sum())
        rows.append(dict(price_basis=basis, factor=factor, horizon=int(horizon), diagnostic="HORIZON",
                         n=len(s), effect=float(s.mean())))
        for year in sorted(set(years)):
            for name, sample in [("YEAR", s[years == year]), ("LEAVE_ONE_YEAR_OUT", s[years != year])]:
                rows.append(dict(price_basis=basis, factor=factor, horizon=int(horizon), diagnostic=name, slice=str(year),
                                 n=len(sample), effect=float(sample.mean()) if len(sample) else None))
            rows.append(dict(price_basis=basis, factor=factor, horizon=int(horizon), diagnostic="ANNUAL_ABSOLUTE_CONTRIBUTION",
                             slice=str(year), share=float(abs(annual[year])/denominator) if denominator else None))
        if factor == "MF043":
            for side, sample in group.groupby("side"):
                side_result = summarize(sample, factor)
                rows.append(dict(side_result, price_basis=basis, horizon=int(horizon), diagnostic="SIDE", slice=str(side)))
    return rows


def parity(events, metrics, expected, audit_events):
    checks = {}
    for factor in FACTORS:
        current = metrics[factor]
        old = expected.loc[expected.master_factor_id.eq(factor)].iloc[0]
        for field in ["event_count", "session_count", "mean_session_score", "median_session_score", "ci95_low", "ci95_high", "raw_p"] + (["baseline_mae", "factor_mae", "baseline_rmse", "factor_rmse"] if factor == "MF038" else []):
            checks[factor+":"+field] = bool(np.isclose(current[field], float(old[field]), rtol=1e-12, atol=1e-12))
    actual = events.loc[events.horizon.eq(6) & events.price_basis.eq("RAW")].copy()
    old = audit_events.loc[audit_events.master_factor_id.isin(FACTORS)].copy()
    actual["timestamp"] = pd.to_datetime(actual.anchor_at, utc=True)
    old["timestamp"] = pd.to_datetime(old.timestamp, utc=True)
    joined = actual.merge(old, left_on=["factor", "timestamp", "price_basis"], right_on=["master_factor_id", "timestamp", "price_basis"], how="outer", indicator=True, validate="one_to_one", suffixes=("_new", "_old"))
    checks["audit_event_identity_keys_and_scores"] = bool(joined._merge.eq("both").all() and np.allclose(joined.score_new, joined.score_old, rtol=1e-12, atol=1e-12))
    checks["audit_factor_values"] = bool(np.allclose(joined.factor_value_new, joined.factor_value_old, rtol=1e-12, atol=1e-12))
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["replay"])
    parser.add_argument("--root", type=Path, default=HERE.parents[1])
    args = parser.parse_args(argv)
    root = args.root.resolve()
    require(sha(HERE/"RESEARCH_CONTRACT.json") == CONTRACT_SHA256, "CONTRACT_IDENTITY_DRIFT")
    contract = json.loads((HERE/"RESEARCH_CONTRACT.json").read_text(encoding="utf-8"))
    output = root/"factor_research/delayed_bar_research/outputs"/RUN_ID
    require(output.resolve().is_relative_to((root/"factor_research/delayed_bar_research").resolve()), "OUTPUT_PATH_ESCAPE")
    reserve(output)  # Existing, failed or consumed attempts are never retried.
    try:
        require(contract["mode"] == "HISTORICAL_REPLAY_ONLY" and contract["factors"] == list(FACTORS), "CONTRACT_DRIFT")
        sources = {}
        for name, digest in contract["source_manifests"].items():
            path = root/name
            require(path.is_file() and sha(path) == digest, "MANIFEST_IDENTITY_DRIFT:"+name)
            manifest = json.loads(path.read_text(encoding="utf-8"))
            sources[name] = digest
            for key in ["source_files", "derived_files", "files"]:
                entries = manifest.get(key, [])
                if isinstance(entries, dict):
                    entries = [dict(v, path=k) for k, v in entries.items()]
                verify_entries(root if key == "source_files" else path.parent, entries)
        import importlib.metadata as metadata
        identity = dict(contract=contract, contract_sha256=sha(HERE/"RESEARCH_CONTRACT.json"),
                        code_sha256=sha(Path(__file__)), manifests=sources,
                        python=sys.version, runtime=sys.executable, platform=platform.platform(),
                        dependencies={p: metadata.version(p) for p in ["numpy", "pandas", "exchange-calendars", "tzdata"]},
                        acquisition_started_at_utc=utc_now(), acquisition_monotonic_ns=time.monotonic_ns())
        write_json(output/"SOURCE_IDENTITY.json", identity)
        actions = pd.read_csv(root/DATA/"CORPORATE_ACTION_EVENTS.csv")
        all_events, exclusions, results = [], [], {}
        for filename, basis in [("RAW_OHLC_CANONICAL.csv", "RAW"), ("RETROSPECTIVE_ADJUSTED_OHLC.csv", "RETROSPECTIVE_ADJUSTED")]:
            source = root/DATA/filename
            digest = sha(source)
            frame = validate(pd.read_csv(source))
            require(frame.session_date.min() == "2018-10-11" and frame.session_date.max() == "2024-12-31", "DATE_RANGE_DRIFT")
            seal(output/"DURABLE_RECEIPTS.jsonl", [dict(source=filename, source_sha256=digest, read_completed_at_utc=utc_now(),
                 read_completed_monotonic_ns=time.monotonic_ns(), historical_availability="UNKNOWN", clock_status="UNVERIFIED")])
            print("Replaying", basis, len(frame), "bars", flush=True)
            events, rejected = replay(frame, actions, basis, output, digest)
            all_events.append(events)
            exclusions.extend(rejected)
            results[basis] = {factor: summarize(events.loc[events.factor.eq(factor) & events.horizon.eq(6)], factor) for factor in FACTORS}
            adjusted = holm([results[basis][factor]["p_for_holm"] for factor in FACTORS])
            for factor, p in zip(FACTORS, adjusted):
                results[basis][factor]["descriptive_holm_p"] = p
            require(sha(source) == digest, "SOURCE_CHANGED_DURING_REPLAY")
        events = pd.concat(all_events, ignore_index=True)
        checks = parity(events, results["RAW"], pd.read_csv(root/OLD_RUN/"FACTOR_RESULTS.csv"), pd.read_csv(root/AUDIT/"ELIGIBLE_EVENT_SCORES.csv"))
        for factor in FACTORS:
            checks[factor+":raw_adjusted_positive_sign"] = results["RAW"][factor]["mean_session_score"] > 0 and results["RETROSPECTIVE_ADJUSTED"][factor]["mean_session_score"] > 0
        write_json(output/"PARITY.json", {"checks": checks, "all_pass": all(checks.values()), "original_run_event_identity": "NOT_IDENTIFIABLE", "event_key_comparison_source": "Later Audit; not original Run"})
        write_json(output/"METRICS.json", results)
        write_json(output/"STABILITY.json", stability(events))
        write_json(output/"EXCLUSIONS.json", exclusions)
        events.to_csv(output/"EVENT_SCORES.csv", index=False)
        summary = dict(engineering_acceptance="PASS" if all(checks.values()) else "PARITY_BLOCKED", evidence=contract["evidence"],
                       run_id=contract["replay_run_id"], independent_predictive_verdict="NOT_TESTED", phase4_started=False,
                       clock_v3_unchanged=True, original_by_q_replaced=False)
        write_json(output/"SUMMARY.json", summary)
    except Exception as exc:
        write_json(output/"FAILURE.json", {"status": "FAILED_ATTEMPT_CONSUMED", "reason": str(exc), "type": type(exc).__name__})
        raise
    finally:
        write_json(output/"MANIFEST.json", {"files": [{"path": p.name, "sha256": sha(p), "size_bytes": p.stat().st_size} for p in sorted(output.iterdir()) if p.is_file()]})
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
