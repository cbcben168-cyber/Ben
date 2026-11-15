"""Read-only V23C research cards. Never derives orders from model quantities."""
from datetime import datetime, timezone
import os
from pathlib import Path

import streamlit as st

from .clock import ET
from .daily_update import latest_completed
from .v23c_signals import SignalStore, instant

ACTION={'INCREASE':'加仓请求','REDUCE':'减仓请求','FLAT':'清仓请求','HOLD':'本次无需调仓','OTHER':'其他模型成交'}
KIND={'REQUEST':'收盘调仓请求','STATE':'收盘状态更新','MODEL_FILL':'TradingView模拟成交'}


def read_rows():
    path=os.environ.get('ICT_V23C_SIGNAL_DB')
    if not path or not Path(path).is_file(): return []
    return SignalStore(path,create=False).read(100)


def status(row,now=None):
    if row['simulation']: return '隔离样本 · 非真实提醒'
    if row['quality']=='STALE': return '延迟送达 · 仅留档'
    if row['quality']=='DATA_GAP': return '依赖资料不齐 · 仅复核'
    now=now or datetime.now(timezone.utc)
    if instant(row['event_at']).astimezone(ET).date().isoformat()<latest_completed(now):
        return '历史记录 · 已过期'
    return '已收到外部研究信号 · 待人工复核'


def event_card(row):
    p=row['payload'];mode='P0-A 原执行' if p['model_mode']==0 else 'P0-B 部分平仓实验'
    with st.container(border=True):
        st.markdown('**'+KIND[row['event']]+' · '+ACTION[row['action']]+'**')
        st.caption(status(row)+' · '+mode+' · 参数标签 '+p['configuration_id'])
        at=instant(row['event_at']).astimezone(ET).strftime('%Y-%m-%d %H:%M:%S 纽约')
        received=instant(row['received_at']).astimezone(ET).strftime('%Y-%m-%d %H:%M:%S 纽约')
        st.caption('策略事件 '+at+' · 接收 '+received)
        if row['event']=='MODEL_FILL':
            st.write('模型成交数量',p['model_fill_qty'],'· 模型成交价',p['model_fill_price'])
            st.caption('这是TradingView撮合模拟器的成交记录；与真实账户、真实委托和真实成交独立。')
        else:
            cols=st.columns(3)
            cols[0].metric('模型目标仓位',f"{p['target_exposure_pct']:g}%")
            cols[1].metric('市场等级',str(p['market_level']))
            cols[2].metric('Boost评分',str(p['boost_score'])+'/9')
            st.caption(f"参考收盘 {p['close']:g} · NASDAQ:QQQ / 1D / RTH")
            st.caption('模型仓位及调仓股数不代表真实账户；请求不等于成交。外部依赖最终性与参数口径尚待核验。')


@st.fragment(run_every=5)
def compact():
    if not os.environ.get('ICT_V23C_SIGNAL_DB'): return
    try: rows=read_rows()
    except (ValueError,OSError):
        st.warning('QQQ V23C独立记录暂不可读，请查看“其他策略”。');return
    latest=next((r for r in rows if r['event'] in ('REQUEST','STATE')),None)
    with st.container(border=True):
        st.markdown('**QQQ V23C · 独立日线策略提醒**')
        if latest:
            st.write(ACTION[latest['action']]+' · '+status(latest))
            st.caption('事件 '+latest['event_at']+' · 模型目标 '+str(latest['payload']['target_exposure_pct'])+'%')
        else:
            st.caption('尚未收到策略信号；手机推送与云端接入尚未验收。')
        def open_page(): st.session_state['desk_page']='其他策略'
        if st.button('查看V23C提醒与记录',key='v23c_details',on_click=open_page): st.rerun()


@st.fragment(run_every=5)
def render():
    st.title('QQQ V23C · 独立策略提醒')
    st.caption('P0执行A/B实验版 · 仅研究提醒与人工复核 · 不属于ICT实时交易资格')
    st.info('手机推送尚未验收：须在TradingView创建有效警报并开启“Notify on App”。网页记录不能证明手机已经收到。')
    st.caption('TradingView按日线确认产生加仓、减仓、清仓请求；当前工作台展示外部上报，不用旧Futu日K重算该策略。')
    try: rows=read_rows()
    except (ValueError,OSError):
        st.error('独立策略记录无法读取；原用户计划与ICT数据库未被打开。');return
    if not rows:
        st.info('尚未收到V23C策略消息。接入完成后，这里会显示真实接收时间和信号来源。')
    requests=[r for r in rows if r['event'] in ('REQUEST','STATE')]
    fills=[r for r in rows if r['event']=='MODEL_FILL']
    st.subheader('调仓请求与日线状态')
    for row in requests[:10]: event_card(row)
    st.subheader('模拟成交 · 独立记录')
    if not fills: st.caption('暂无模拟成交记录。不能从调仓请求推断成交。')
    for row in fills[:10]: event_card(row)
    with st.expander('提醒口径与接入状态'):
        st.write('原Pine计算和订单调用保持不变。A/B开关仍由TradingView参数决定。')
        st.write('REC只是恢复加仓条件；只有模型产生调仓请求才标记加仓、减仓或清仓。')
        st.write('参数变化后必须重新创建TradingView警报，旧警报不会自动跟随图表修改。')
        st.write('公网接入尚未部署；当前仅支持经认证的本机独立接收器。延迟消息保留为过期记录，重复消息不重复入库。')
        st.caption('真实账户持仓、资金和订单均未接入。手机推送送达、Pine云端编译及实际前向对账须另有真实证据。')
