"""Recompute prior-day ranges from saved, isolated minute rows; no network."""
import json
import sqlite3
import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk.analytics import key_levels, aggregate_rth
from desk.clock import now_et, previous_day

root = Path(__file__).resolve().parents[1]
with sqlite3.connect(root/'data'/'desk.sqlite3') as c:
    rows = c.execute("SELECT payload FROM bars WHERE symbol='US.SPY' AND period='1M'").fetchall()
f = pd.DataFrame(json.loads(row[0]) for row in rows)
if f.empty:
    raise SystemExit('No saved real minute data')
f['ts'] = pd.to_datetime(f.ts, utc=True).dt.tz_convert('America/New_York')
day = previous_day(now_et().date())
levels = key_levels(f, day, now_et())
independent = {}
for n in (5,15,30):
    subset = f[(f.ts.dt.date == day) & (f.session == 'RTH')].sort_values('ts').head(n)
    value = levels[f'OR_{n}']
    assert len(subset) == n and value['high'] == subset.high.max() and value['low'] == subset.low.min()
    independent[f'OR_{n}'] = dict(high=value['high'],low=value['low'],rows=n)
bars = aggregate_rth(f,240,now_et())
report = dict(at=now_et().isoformat(),source='SAVED_FUTU_OPEND_1M',symbol='US.SPY',
              day=str(day),independent_or_crosscheck=independent,derived_4h_rows=len(bars),
              derived_4h_durations=sorted(bars.duration_minutes.unique().tolist()),
              session_counts=f.session.value_counts().to_dict(),finality='VENDOR_FINALITY_UNVERIFIED')
(root/'data'/'saved-data-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
