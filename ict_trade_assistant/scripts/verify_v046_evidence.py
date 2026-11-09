"""Read-only real archive/indicator/reference and intraday-boundary audit."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from desk.clock import ET
from desk.experiment import replay_cutoff
from desk.futu_daily import FutuDailyArchive, CONTRACT as DAILY
from desk.futu_hourly import FutuHourlyArchive, session_grid, CONTRACT
from desk.market_state import market_state
from desk.ema_layers import ema_points
from desk.historical_prices import references


def verify(archive, daily, probes, reference_asof=None):
    reference_asof = pd.Timestamp(reference_asof) if reference_asof else pd.Timestamp.now(tz='UTC')
    manifest = json.loads((archive/'manifest.json').read_text(encoding='utf-8'))
    result = dict(symbols={}, boundary_probes=[], archive=str(archive.resolve()),
                  manifest_sha256=hashlib.sha256((archive/'manifest.json').read_bytes()).hexdigest())
    for code in manifest['symbols']:
        meta, hour = FutuHourlyArchive(archive).read(code)
        dm, day = FutuDailyArchive(daily).read(code)
        asof = replay_cutoff(pd.Timestamp(dm['last']).date())
        state, completed = market_state(hour, '1H', asof, CONTRACT)
        if meta['status'] == 'PASS':
            assert state['trend'] != 'UNKNOWN', state['reason']
            assert len(completed) >= 50 and completed.end_at.max() + pd.Timedelta(minutes=2) <= asof
            points = ema_points(completed, '1H', asof, CONTRACT)
            assert points.short.iloc[-1] == state['ema20']
            assert points.long.iloc[-1] == state['ema50']
        ref = references(day, reference_asof, DAILY, dm, hour, meta)
        assert len([r for r in ref['levels'] if not r['name'].startswith('已确认')]) == 3
        result['symbols'][code] = dict(hourly=meta, indicators=state, references=ref,
            native_first=hour.ts.iloc[0] if not hour.empty else None,
            native_last=hour.end_at.iloc[-1] if not hour.empty else None)
    hashes = json.loads((probes/'manifest.json').read_text())
    for name, sha in hashes.items():
        assert hashlib.sha256((probes/name).read_bytes()).hexdigest() == sha
    for date in ('2025-11-28', '2026-11-06'):
        minute = json.loads((probes/(date+'-K_1M.json')).read_text(encoding='utf-8'))
        hourly = json.loads((probes/(date+'-K_60M.json')).read_text(encoding='utf-8'))
        m = pd.DataFrame(minute['records'])
        m['end_at'] = pd.to_datetime(m.time_key).dt.tz_localize(ET).dt.tz_convert('UTC')
        grid = session_grid(date,date)
        assert list(m.end_at) == list(pd.date_range(grid[0][0]+pd.Timedelta(minutes=1),grid[-1][1],freq='min'))
        assert len(hourly['records']) == len(grid)
        for (start, end), h in zip(grid, hourly['records']):
            assert pd.Timestamp(h['time_key']).tz_localize(ET).tz_convert('UTC') == end
            group=m.loc[(m.end_at>start)&(m.end_at<=end)]
            actual=dict(open=group.open.iloc[0],high=group.high.max(),low=group.low.min(),
                        close=group.close.iloc[-1],volume=group.volume.sum())
            errors={k:float(actual[k]-h[k]) for k in actual}
            assert all(abs(errors[k]) <= 1e-6 for k in ('open','high','low','close')), errors
            result['boundary_probes'].append(dict(date=date,start=start,end=end,minute_count=len(group),
                actual=actual,native_hourly={k:h[k] for k in actual},errors=errors,
                volume_reconciled=abs(errors['volume'])<=1.,
                timestamp_interpretation='1M及60M均为结束标签；映射至RTH开始网格'))
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--daily',type=Path,required=True)
    parser.add_argument('--probes',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--reference-asof',help='UTC/offset timestamp for latest-mode reference evidence')
    args=parser.parse_args()
    evidence=verify(args.archive,args.daily,args.probes,args.reference_asof)
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(evidence,stream,ensure_ascii=False,indent=2,default=str)
    print('PASS',len(evidence['symbols']),'symbols;',len(evidence['boundary_probes']),'boundary candles')
