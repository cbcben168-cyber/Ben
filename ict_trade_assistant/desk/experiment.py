"""Versioned historical experiments; no formal settings or trading authority."""
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sqlite3

from .clock import bounds

VERSION = 'v0.4.4.1'


@dataclass(frozen=True)
class Experiment:
    ema_short: int = 20
    ema_long: int = 50
    atr_period: int = 14
    sideways_atr: float = .50
    candidate_atr: float = .25

    def __post_init__(self):
        limits = dict(ema_short=(5, 30), ema_long=(35, 50), atr_period=(7, 20),
                      sideways_atr=(.10, 1.50), candidate_atr=(.05, 1.00))
        for key, (low, high) in limits.items():
            value = getattr(self, key)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not low <= value <= high
                    or (key in ('ema_short', 'ema_long', 'atr_period') and not isinstance(value, int))):
                raise ValueError('实验参数超出范围或格式错误：' + key)
        if self.ema_short >= self.ema_long:
            raise ValueError('短期EMA必须小于长期EMA')


BASELINE = Experiment()


def replay_cutoff(day):
    """The chosen NYSE session close plus the unchanged two minute quarantine."""
    session = bounds(day)
    if session is None:
        raise ValueError('所选日期不是纽约交易日，请选择有归档的交易日。')
    return session[1] + timedelta(minutes=2)


def completed_snapshot(data, asof):
    """Copy and truncate before calling any historical observation/structure code."""
    from .market_state import daily_prefix
    result = dict(data)
    # Labels keep the date selector reversible; future prices never enter a calculation.
    date_keys = ('daily', 'independent_daily') if not data['daily'].empty else ('minute', 'independent_daily')
    result['_archive_dates'] = data.get('_archive_dates') or sorted({
        day for key in date_keys
        if key in data and not data[key].empty for day in data[key].ts.dt.date})
    result['daily'] = daily_prefix(data['daily'], asof)
    minute = data['minute']
    if not minute.empty:
        minute = minute.loc[minute.eligible.eq(True)
                            & (minute.ts + timedelta(minutes=3) <= asof)].copy()
    result['minute'] = minute
    result['health'] = dict(quality='UNAVAILABLE', reason='历史实验，不使用实时报价',
                            source=data.get('health', {}).get('source', 'UNKNOWN'),
                            received_at=asof.isoformat(), right='UNKNOWN')
    if 'independent_daily' in result:
        result['independent_daily'] = daily_prefix(result['independent_daily'], asof)
    if data.get('coverage'):
        result['coverage'] = dict(data['coverage'], last=str(result['daily'].ts.iloc[-1].date())
                                  if not result['daily'].empty else '资料不足')
    return result


def distance_result(data, state, config, period):
    """Reuse existing native daily + complete 1M verification, then simulate distance.

    No manual zones, formal settings, ICT qualification, or live price are inputs.
    Only same-source native DAY experiments have a qualified daily price basis.
    """
    from .observations import build_observation
    result = dict(eligible=None, label='资料不足', reason='缺少同源、完整分钟验证的原生日K价格基准。',
                  distance=None, threshold=config.candidate_atr, key=None)
    if state['trend'] == 'UNKNOWN' or not state.get('atr14'):
        result['reason'] = state.get('reason', '历史环境无法计算。')
        return result
    if period != '1D' or not data.get('history_origin'):
        result['reason'] = '此来源或周期没有已验证的历史候选价格基准；不产生ICT资格。'
        return result
    # Evaluate at the data's own last close, never at a later wall-clock session.
    observed = state['at'] + timedelta(minutes=2)
    snapshot = completed_snapshot(data, observed)
    observation = build_observation('HISTORY', snapshot, {'zones': {}, 'candidate_atr': .25}, observed)
    monitors = observation.get('monitors', [])
    if observation['status'] != 'AVAILABLE' or not monitors:
        result['reason'] = observation['reason'] if not monitors else result['reason']
        return result
    price = observation['reference_price']
    row = min(monitors, key=lambda r: (max(r['low']-price, price-r['high'], 0), r['priority'], r['key']))
    gap = max(row['low']-price, price-row['high'], 0)
    distance = gap / state['atr14']
    eligible = bool(distance <= config.candidate_atr)
    result.update(eligible=eligible, label='进入历史观察' if eligible else '超出观察距离',
                  reason='仅模拟关键价距离筛选，不代表ICT确认或交易许可。',
                  distance=distance, gap=gap, price=price, key=row['key'],
                  price_at=state['at'], atr=state['atr14'])
    return result


class ExperimentStore:
    """A separate SQLite file. Baseline is a constant and is never a database row."""
    def __init__(self, path):
        self.path = Path(path)

    def names(self):
        if not self.path.exists():
            return ['Baseline']
        with closing(sqlite3.connect(self.path, timeout=15)) as connection:
            return ['Baseline'] + [r[0] for r in connection.execute('SELECT name FROM experiments ORDER BY name')]

    def save(self, name, config):
        name = name.strip()
        if not name or len(name) > 60 or name.casefold() == 'baseline':
            raise ValueError('请使用1–60字的实验名称；Baseline不可覆盖。')
        config = Experiment(**asdict(config))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=15)) as connection, connection:
            connection.execute('CREATE TABLE IF NOT EXISTS experiments(name TEXT PRIMARY KEY,version TEXT,parameters TEXT,updated_at TEXT)')
            connection.execute('INSERT OR REPLACE INTO experiments VALUES(?,?,?,?)',
                               (name, VERSION, json.dumps(asdict(config), allow_nan=False),
                                datetime.now(timezone.utc).isoformat()))

    def load(self, name):
        return self.load_profile(name)['config']

    def load_profile(self, name):
        """Return values and their stored version atomically; retain v0.4.4 profiles."""
        if name == 'Baseline':
            return dict(config=BASELINE, version=VERSION)
        with closing(sqlite3.connect(self.path, timeout=15)) as connection:
            row = connection.execute('SELECT version,parameters FROM experiments WHERE name=?', (name,)).fetchone()
        if not row or row[0] not in ('v0.4.4', VERSION):
            raise ValueError('参数组合不存在或版本不兼容。')
        return dict(config=Experiment(**json.loads(row[1])), version=row[0])
