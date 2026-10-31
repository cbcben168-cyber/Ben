"""capture: 真实只读OpenD证据；Streamlit入口: 固定真实快照、独立数据库。"""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'data/v02_acceptance'


def capture():
    from desk.provider import Provider
    from desk.clock import now_et
    from desk.observations import SYMBOLS
    OUT.mkdir(parents=True,exist_ok=True)
    provider=Provider(); snapshots={}
    try:
        for symbol in (*SYMBOLS,'US.VIX'):
            data=provider.fetch(symbol)
            snapshots[symbol]={k:v.to_dict('records') if k in ('minute','daily') else v for k,v in data.items()}
            print(symbol,data['health']['quality'],len(data['minute']),len(data['daily']),flush=True)
    finally:
        provider.close()
    (OUT/'real_snapshots.json').write_text(json.dumps(snapshots,default=str,ensure_ascii=False),encoding='utf-8')
    analyse()


def read_snapshots():
    import pandas as pd
    snapshots=json.loads((OUT/'real_snapshots.json').read_text(encoding='utf-8'))
    for saved in snapshots.values():
        for period in ('minute','daily'):
            saved[period]=pd.DataFrame(saved[period])
            if not saved[period].empty: saved[period]['ts']=pd.to_datetime(saved[period]['ts'],utc=True).dt.tz_convert('America/New_York')
    return snapshots


def analyse():
    from desk.clock import now_et
    from desk.observations import build_observation, SYMBOLS, ranked
    from desk.store import DEFAULTS
    snapshots=read_snapshots()
    observations={s:build_observation(s,snapshots[s],DEFAULTS,now_et()) for s in SYMBOLS}
    report=dict(captured_at=now_et().isoformat(),observations=observations,candidates=ranked(observations),
                live_acceptance='PENDING_LIVE_ACCEPTANCE',source='真实本机OpenD，只调用行情接口；未使用模拟价格')
    (OUT/'source_verification.json').write_text(json.dumps(report,default=str,ensure_ascii=False,indent=2),encoding='utf-8')
    print('candidate_count',len(report['candidates']),flush=True)


def ui():
    import runpy
    import pandas as pd
    import streamlit as st
    import desk.store as stores
    import desk.provider as providers
    if not hasattr(stores,'_V02Original'): stores._V02Original=stores.Store
    class AcceptanceStore(stores._V02Original):
        def __init__(self,*a,**kw): super().__init__(OUT/'acceptance.sqlite3')
    def fetch(self,symbol):
        return read_snapshots()[symbol]
    stores.Store=AcceptanceStore
    providers.Provider.fetch=fetch
    st.warning('真实OpenD历史快照验收 · 实时状态按当前时间重验 · 独立验收数据库 · 无交易账户连接')
    runpy.run_path(str(ROOT/'app.py'),run_name='__main__')


if __name__=='__main__':
    if 'capture' in sys.argv: capture()
    elif 'analyse' in sys.argv: analyse()
    else: ui()
