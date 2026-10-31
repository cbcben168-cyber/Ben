"""后续 ICT 检测器的数据契约。本轮没有自动结构检测器。"""
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
import math

ICT_EVENT_TYPES = frozenset({'SWEEP', 'RECLAIM', 'MSS', 'FVG', 'CE', 'INVALIDATED'})


@dataclass(frozen=True)
class ICTEvent:
    kind: str
    symbol: str
    timeframe: str
    direction: str
    key_price: float
    occurred_at: datetime
    confirmed_at: Optional[datetime]
    source: str
    parameter_version: str
    status: str
    invalidation: str
    bar_end: datetime
    completed_bar: bool = False

    def __post_init__(self):
        if self.kind not in ICT_EVENT_TYPES or self.status not in {'FORMING', 'CONFIRMED', 'INVALIDATED'}:
            raise ValueError('事件类型或状态不合法')
        if (not self.symbol or not self.timeframe or not self.source or not self.parameter_version
                or not self.invalidation or self.direction not in {'LONG', 'SHORT', 'UNKNOWN'}
                or not math.isfinite(self.key_price) or self.key_price <= 0):
            raise ValueError('事件证据字段不完整')
        for ts in (self.occurred_at, self.bar_end, self.confirmed_at):
            if ts is not None and (ts.tzinfo is None or ts.utcoffset() is None):
                raise ValueError('事件时间必须带时区')
        if self.confirmed_at and self.confirmed_at < self.occurred_at:
            raise ValueError('确认时间早于发生时间')
        if self.status == 'CONFIRMED' and (not self.completed_bar or self.confirmed_at is None
                                             or self.confirmed_at < self.bar_end):
            raise ValueError('未完成K线不得确认事件')

    def payload(self):
        return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in asdict(self).items()}
