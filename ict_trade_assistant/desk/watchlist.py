"""User-owned universe; the AUM preset is a dated user-supplied list, not a live feed."""
import re

DEFAULT_SYMBOLS = ('US.SPY', 'US.QQQ', 'US.IWM', 'US.SOXX')
TOP20 = tuple('US.' + s for s in 'VOO IVV SPY VTI QQQ VEA VUG IEFA VTV SPYM BND VXUS IEMG VGT GLD AGG IWF IJH VWO XLK'.split())
PRESET = dict(id='US_ETF_AUM_TOP20_20261103', source='用户指定固定名单（2026-11-03任务说明）',
              recorded_at='2026-11-03', ranking_basis='美国ETF资产管理规模（AUM），按用户给定顺序',
              as_of='原始AUM统计日期未提供', verified_live=False, symbols=list(TOP20))


def normalize_symbol(value):
    code = value.strip().upper()
    code = code if code.startswith('US.') else 'US.' + code
    if not re.fullmatch(r'US\.[A-Z][A-Z0-9.-]{0,14}', code):
        raise ValueError('请输入美股代码，例如SPY、US.AAPL或BRK.B。')
    if code == 'US.VIX':
        raise ValueError('VIX仅作背景，不加入观察名单或候选排名。')
    return code


def initial_entries(codes):
    return [dict(symbol=c, enabled=True, group='默认' if c in DEFAULT_SYMBOLS else '自选')
            for c in dict.fromkeys(normalize_symbol(c) for c in codes if c.strip().upper() not in ('VIX','US.VIX'))]


def universe(symbols):
    return tuple(dict.fromkeys(c for c in symbols if c != 'US.VIX'))
