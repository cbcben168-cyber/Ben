"""Responsive quote-only workspace. Signal definitions remain in analytics."""
import json
from zoneinfo import ZoneInfo
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from .i18n import zh, details, TEXT
from .clock import now_et, session
from .analytics import aggregate_rth, key_levels, observe, previous_week_levels
from .plans import active_plan, risk_reward, evaluate_plan
from .plan_editor import editors
from .diagnostics import panel
from .observations import build_observation, ranked, record_events, live_health, regions, price_basis_comparison, SYMBOLS
from .ict_v03 import scan as scan_ict, VERSION as ICT_VERSION
from .ict_view import add_event_layers, review_text, event_rows, STATUS as ICT_STATUS
from .decision import prioritize, LABELS as DECISION_LABELS

CSS = '''<style>
.block-container{padding:4rem 1.25rem 1rem;max-width:none;font-size:16px}
.block-container{container-type:inline-size;container-name:desk-main}
.st-key-deskgrid{display:grid!important;grid-template-columns:minmax(0,24fr) minmax(0,49fr) minmax(0,27fr);gap:16px;align-items:start}
.st-key-deskgrid [data-testid="stLayoutWrapper"]:has(>.st-key-radar){grid-column:1;grid-row:1}.st-key-deskgrid [data-testid="stLayoutWrapper"]:has(>.st-key-chart){grid-column:2;grid-row:1 / span 2}
.st-key-deskgrid [data-testid="stLayoutWrapper"]:has(>.st-key-decision){grid-column:3;grid-row:1}.st-key-deskgrid [data-testid="stLayoutWrapper"]:has(>.st-key-plans){grid-column:1;grid-row:2}.st-key-deskgrid [data-testid="stLayoutWrapper"]:has(>.st-key-alerts){grid-column:3;grid-row:2}
.st-key-deskgrid>div{min-width:0} button{min-height:38px} p{overflow-wrap:anywhere}
.st-key-deskgrid>div:has(>.st-key-leftstack),.st-key-deskgrid>div:has(>.st-key-rightstack),.st-key-leftstack,.st-key-rightstack{display:contents}
.st-key-decision{gap:12px!important}
.st-key-decision [data-testid="stMarkdownContainer"] p{font-size:16px;line-height:1.55}
.st-key-decision [data-testid="stCaptionContainer"] p{font-size:14px}
.st-key-radar h3,.st-key-chart h3,.st-key-decision h3{font-size:1.35rem}
@media(max-aspect-ratio:1/1){
.st-key-deskgrid{grid-template-columns:minmax(0,60fr) minmax(0,40fr)}
.st-key-deskgrid>div:has(>.st-key-leftstack),.st-key-deskgrid>div:has(>.st-key-rightstack){display:block;align-self:start;min-width:0}
.st-key-leftstack,.st-key-rightstack{display:flex;flex-direction:column;gap:16px;min-width:0}
.st-key-deskgrid [data-testid="stLayoutWrapper"]:has(>.st-key-radar){grid-column:1 / -1;grid-row:1}
.st-key-deskgrid>div:has(>.st-key-leftstack){grid-column:1;grid-row:2}
.st-key-deskgrid>div:has(>.st-key-rightstack){grid-column:2;grid-row:2}
}
@container desk-main (max-width:1119px){
.st-key-deskgrid{display:flex!important;flex-direction:column}
.st-key-deskgrid>div:has(>.st-key-leftstack),.st-key-deskgrid>div:has(>.st-key-rightstack),.st-key-leftstack,.st-key-rightstack{display:contents}
.st-key-deskgrid [data-testid="stLayoutWrapper"]:has(>.st-key-radar){order:0;width:100%}
.st-key-deskgrid [data-testid="stLayoutWrapper"]:has(>.st-key-chart){order:1;width:100%}
.st-key-deskgrid [data-testid="stLayoutWrapper"]:has(>.st-key-decision){order:2;width:100%}
.st-key-deskgrid [data-testid="stLayoutWrapper"]:has(>.st-key-plans){order:3;width:100%}
.st-key-deskgrid [data-testid="stLayoutWrapper"]:has(>.st-key-alerts){order:4;width:100%}
}
</style>'''


def fresh(data, now):
    return live_health(data['health'], now)


@st.cache_data(max_entries=96,show_spinner=False)
def chart_data(minute,daily,period,at):
    levels=key_levels(minute,at.date(),at) if not minute.empty else {}
    levels['PREVIOUS_WEEK']=previous_week_levels(daily,at.date(),at)
    chart=daily[daily.eligible].copy() if period=='1D' and not daily.empty else pd.DataFrame()
    if period!='1D' and not minute.empty:
        chart=aggregate_rth(minute,{'15m':15,'1H':60,'4H':240}[period],at)
    return chart,levels


def select_symbol(code):
    st.session_state.desk_symbol=code


@st.cache_data(max_entries=24,show_spinner=False)
def historical_ict(symbol,minute,at):
    return scan_ict(symbol,minute,at)


def select_candidate(code, key):
    st.session_state.desk_symbol=code
    st.session_state.desk_candidate=(code,key)


def render(store, settings, market_data):
    st.markdown(CSS, unsafe_allow_html=True)
    codes = list(dict.fromkeys(settings['watchlist'] + [p['symbol'] for p in store.plans()] + ['US.SPY','US.QQQ','US.IWM','US.SOXX','US.VIX']))
    if 'desk_symbol' not in st.session_state:
        st.session_state.desk_symbol = 'US.SPY'
    with st.expander(TEXT['文案30']):
        st.caption(TEXT['文案31'])
        auto = st.checkbox(TEXT['文案32'], value=False)
        if st.button(TEXT['文案33']):
            market_data.clear()
            st.session_state['manual_cycle']=st.session_state.get('manual_cycle',0)+1
        st.selectbox(TEXT['文案34'], codes, key='desk_symbol')

    # 首屏加载期间短轮询；完成后按数据刷新周期更新，不重复重绘静态控件。
    warm_cycle=('auto',int(now_et().timestamp()//settings['refresh_seconds']),settings['refresh_seconds']) if auto else ('manual',st.session_state.get('manual_cycle',0))
    for code in codes:market_data(code,warm_cycle)
    initializing=bool(getattr(market_data,'loading',lambda:False)())

    @st.fragment(run_every=2 if initializing else settings['refresh_seconds'] if auto else None)
    def body():
        now = now_et()
        selected = st.session_state.desk_symbol
        all_codes = list(dict.fromkeys(codes+[selected]))
        cycle=('auto',int(now.timestamp()//settings['refresh_seconds']),settings['refresh_seconds']) if auto else ('manual',st.session_state.get('manual_cycle',0))
        data={}
        for c in all_codes:
            try:data[c]=market_data(c,cycle)
            except Exception:
                import logging
                logging.getLogger('ict.stability').exception('标的快照展示失败 symbol=%s',c)
                data[c]=dict(health=dict(quality='UNAVAILABLE',reason='该标的快照暂不可用，请查看诊断日志。',received_at=now.isoformat()),minute=pd.DataFrame(),daily=pd.DataFrame(),errors=[])
        health = {c:fresh(d, now) for c,d in data.items()}
        observations={c:build_observation(c,data[c],settings,now,active_plan(store,c) or settings['zones'].get(c)) for c in all_codes if c!='US.VIX'}
        for observation in observations.values():
            store.observation(observation)
            record_events(store,observation)
        if 'US.VIX' in health:
            vh=health['US.VIX']
            store.transition('SYSTEM','US.VIX','DATA_HEALTH',vh['quality'],now.isoformat(),vh['reason'],vh,'health')
        observation=observations[selected] if selected in observations else None
        reports={c:historical_ict(c,data[c]['minute'],now.replace(second=0,microsecond=0)) for c in SYMBOLS if c in observations}
        decisions=prioritize(observations,reports,now)
        st.session_state['v04_decisions']={r['symbol']:r for r in decisions}
        rows=[dict(r['focus'],decision=r) for r in decisions if r['focus']]
        chosen=st.session_state.get('desk_candidate')
        focus=next((r for r in (regions(observation) if observation else []) if chosen==(selected,r['key'])),None)
        if focus is None: focus=next((r for r in rows if r['symbol']==selected),None)
        h=health[selected]; d=data[selected]; plan=active_plan(store,selected)
        ict=reports.get(selected) or historical_ict(selected,d['minute'],now.replace(second=0,microsecond=0))
        decision=next((r for r in decisions if r['symbol']==selected),None)
        zone=plan or settings['zones'].get(selected)
        for p in store.plans():
            if p['symbol'] in health: evaluate_plan(store,p,health[p['symbol']],now.date(),settings['distance_bps'])
        st.caption(f"◈ ICT 交易工作台 V2 · {now:%H:%M:%S %Z} / {now.astimezone(ZoneInfo('Asia/Hong_Kong')):%H:%M:%S HKT} · {zh(session(now))} · ● {zh(h['quality'])} · {selected}")
        if h.get('loading'):
            st.info('正在连接或读取行情；尚未取得有效报价，暂不进行新增入场审查。')
        elif observation and observation['mode']=='PREPARATION' and observation['status']=='AVAILABLE':
            st.info('盘前／闭市准备模式 · 闭市期间报价正常无更新不等于OpenD故障；历史距离不属于实时到价。实时入场审查关闭。')
        elif h['quality'] != 'AVAILABLE':
            st.error(zh('DATA_BLOCKED')+' · '+zh(h['reason'])+' · '+zh('NO NEW ACTION'))
        if observation:
            st.caption('观察数据：'+observation['status']+' · '+observation['reason']+' · 所属交易日 '+observation['trading_day']+' · 参数版本 '+observation['parameter_version'])
            if d.get('opend_status')=='UNAVAILABLE' or d.get('retained_periods'):
                st.warning('OpenD读取异常，历史准备使用保留数据 · '+zh(h['reason']))
        markets=st.columns(5)
        for col,c in zip(markets,['US.SPY','US.QQQ','US.IWM','US.SOXX','US.VIX']):
            mh=health[c]
            col.write(f"**{c[3:]}** · {mh.get('price','—')}")
            col.caption(zh(mh['quality']) + (' · 风险背景' if c=='US.VIX' else ' · 原始报价，过期值非实时'))
        with st.expander(TEXT['文案35']):
            st.json(details(health))
            st.write('后台读取队列与恢复状态')
            st.json(getattr(market_data,'diagnostics',lambda:{})())
        with st.container(key='deskgrid'):
            with st.container(key='radar', border=True), panel('候选区'):
                st.subheader('证券观察优先级')
                st.caption(f'观察证券 {sum(c in observations for c in SYMBOLS)} 只 · 关键价位观察 {sum(len(o["monitors"]) for c,o in observations.items() if c in SYMBOLS)} 条 · 当前展示 {len(rows[:5])} 只')
                st.caption('按不同证券排名；距离仅表示观察优先级，不是交易成功概率。闭区间相交（含端点相等）合并为共振区域，原始价位全部保留。')
                for n,r in enumerate(rows[:5],1):
                    c=r['symbol']; label=r['region_label']
                    if r.get('historical_day'): label+='（'+r['historical_day']+'历史）'
                    state='区域内' if r['state']=='INSIDE' else '接近关键价'
                    st.button(f"{n} · {c[3:]} · {label} · {state}",key='pick_'+c+'_'+r['key'],width='stretch',on_click=select_candidate,args=(c,r['key']))
                    st.caption(f"区域 {r['low']:g}–{r['high']:g} · ${r['gap']:.2f} / {r['atr_distance']:.3f} ATR · "+('方向未定' if r['direction']=='UNKNOWN' else zh(r['direction'])))
                    st.caption(r['distance_basis']+' · '+r['next_action'])
                    st.caption('当前阶段：'+DECISION_LABELS[r['decision']['stage']]+' · '+r['decision']['next_condition'])
                    st.caption('基准时间 '+r['quote_at']+' · 有效至 '+r['valid_until'])
                    with st.expander(c[3:]+' 其他区域与全部原始价位'):
                        for other in regions(observations[c]):
                            st.write(other['region_label']+f" · {other['low']:g}–{other['high']:g} · {other['atr_distance']:.3f} ATR")
                            st.button('关注 '+other['region_label'],key='region_'+c+'_'+other['key'],on_click=select_candidate,args=(c,other['key']))
                        st.dataframe(pd.DataFrame(observations[c]['monitors'])[['key','low','high','atr_distance']].rename(columns={'key':'原始价位','low':'下限','high':'上限','atr_distance':'距离ATR'}),hide_index=True)
                if not rows: st.info('当前无合资格候选：检查数据完整性及关键价位距离。')
                with st.expander('历史价格口径与排序差异'):
                    st.caption('历史排序采用 Futu 原生日 K 收盘；日 K 与末分钟差异原因尚未裁定，未调整原始行情。名次变化或候选资格变化均列出供人工复核。')
                    st.dataframe(pd.DataFrame(price_basis_comparison(observations,settings['candidate_atr'])),hide_index=True)
                    for c,o in observations.items():
                        if o.get('close_verification'): st.write(c, o['close_verification'])
                if rows and selected not in [r['symbol'] for r in rows[:5]]: st.caption(TEXT['文案52'])
            with st.container(key='leftstack'):
                with st.container(key='chart',border=True), panel('图表'):
                    st.subheader(selected[3:]+' · 常规交易时段')
                    period=st.radio(TEXT['文案38'],['15m','1H','4H','1D'],index=1,horizontal=True,format_func=lambda v: {'15m':'15分钟','1H':'1小时','4H':'4小时','1D':'日线'}[v])
                    with st.expander(TEXT['图层控制']):
                        layers=st.multiselect('关键价格线图层',['前日高低','前周高低','开盘区间','人工计划'],default=['前日高低','前周高低','开盘区间','人工计划'] if settings['layers'] else [],key='price_layers')
                        st.caption(TEXT['价格线说明'])
                    minute,daily=d['minute'],d['daily']
                    chart,levels=chart_data(minute,daily,period,now.replace(second=0,microsecond=0))
                    if observation: levels=observation['levels']
                    st.caption('图表周期：'+period+' · 柱数：'+str(len(chart))+' · 最近柱：'+(str(chart.ts.iloc[-1]) if not chart.empty else '无可用数据'))
                    if d.get('retained_periods'):st.warning('历史快照保留中（STALE 行情过期） · '+str(d.get(('daily' if period=='1D' else 'minute')+'_snapshot_at','时间未知')))
                    if not chart.empty:
                        fig=go.Figure(go.Candlestick(x=chart.ts.map(str),open=chart.open,high=chart.high,low=chart.low,close=chart.close,name={'15m':'15分钟','1H':'1小时','4H':'4小时','1D':'日线'}[period]))
                        for name,v in levels.items():
                            group='前日高低' if name=='PREVIOUS_RTH' else '前周高低' if name=='PREVIOUS_WEEK' else '开盘区间' if name.startswith('OR_') else None
                            if group not in layers: continue
                            for side,label in [('high','高点'),('low','低点')]:
                                if v[side] is not None:
                                    title={'PREVIOUS_RTH':'前日','PREVIOUS_WEEK':'前周'}.get(name,name.replace('OR_','开盘区间 '))+label
                                    fig.add_scatter(x=[str(chart.ts.iloc[0]),str(chart.ts.iloc[-1])],y=[v[side]]*2,mode='lines',line=dict(dash='dot',width=1),name=title,hovertemplate=title+'：%{y:.2f}<extra></extra>')
                        if zone and '人工计划' in layers:
                            fig.add_hrect(y0=zone['low'],y1=zone['high'],opacity=.12,fillcolor='cyan')
                            if zone.get('invalid'): fig.add_hline(y=zone['invalid'],line_color='red')
                            if plan: fig.add_hrect(y0=plan['target_low'],y1=plan['target_high'],opacity=.10,fillcolor='green')
                        if focus:
                            fig.add_hline(y=focus['low'],line_color='orange',annotation_text='当前关注 '+focus.get('region_label',focus['key']))
                            if focus['high']!=focus['low']: fig.add_hline(y=focus['high'],line_color='orange')
                        if period=='1H':add_event_layers(fig,ict)
                        fig.update_layout(template='plotly_dark',height=560,margin=dict(l=8,r=12,t=12,b=24),showlegend=False,font=dict(size=14),yaxis=dict(side='right',automargin=True),xaxis=dict(automargin=True),xaxis_rangeslider_visible=False,uirevision=selected+period)
                        st.plotly_chart(fig,width='stretch',key='mainchart')
                    else: st.info(TEXT['文案53'])
                    st.caption(TEXT['图表来源摘要'])
                    with st.expander('周期数据核对（最近三根真实聚合柱）'):
                        if not chart.empty:
                            st.dataframe(chart.tail(3)[[c for c in ['ts','open','high','low','close','duration_minutes'] if c in chart]].rename(columns=dict(ts='纽约时间',open='开盘',high='最高',low='最低',close='收盘',duration_minutes='实际聚合分钟数')),hide_index=True)
                    with st.expander('关键价格与时段证据'):
                        st.json(details(observation or levels))
                    st.caption('ICT v0.3 · 仅1小时历史观察，标记位于确认时点；4小时与日线自动识别未启用。供应商最终性未验证。')
                    with st.expander('历史ICT事件与确认时间（非实时提醒）'):
                        st.caption(ICT_VERSION+' · '+ict['reason'])
                        records=event_rows(ict)
                        if records:st.dataframe(pd.DataFrame(records),hide_index=True)
                        else:st.info('未知／无满足定义的历史结构事件；不补造信号。')
                        rejected=[e for e in ict['sweeps'] if e['status']=='INVALIDATED']
                        if rejected:
                            st.caption('收盘未收回的扫荡候选（不进入已确认状态链）')
                            st.dataframe(pd.DataFrame([dict(方向='多向' if e['direction']=='LONG' else '空向',流动性水平=e['level'],扫荡极值=e['extreme'],确认时间=e['confirmed_at'],失效原因=e['invalidation_reason']) for e in rejected]),hide_index=True)
                        if ict['fvgs']:
                            st.dataframe(pd.DataFrame([dict(下界=z['low'],上界=z['high'],中点=z['ce'],状态=ICT_STATUS[z['status']],确认时间=z['confirmed_at'],失效原因=z['invalidation_reason']) for z in ict['fvgs']]),hide_index=True)
                with st.container(key='plans',border=True), panel('人工计划'):
                    st.subheader(TEXT['文案49'])
                    st.info(TEXT['文案50'])
                    for p in store.plans():
                        st.write(p['symbol']+' · 人工计划 · '+('已取消' if p['status']=='CANCELLED' else '待人工复核')+' · 第'+str(p['version'])+'版')
                        st.caption(f"入场 {p['low']}–{p['high']} · 失效 {p['invalid']} · 目标 {p['target_low']}–{p['target_high']}")
                    with st.expander('人工关注区域与计划详情'):
                        for c,z in settings['zones'].items(): st.write(c+' · 草稿人工关注区域',details(z))
                        st.json(details(store.plans()))
            with st.container(key='rightstack'):
                with st.container(key='decision',border=True), panel('决策卡'):
                    state,reason=observe(h.get('price'),h['quality'],zone,settings['distance_bps'])
                    st.subheader(selected[3:]+' · '+(zh(zone['direction']) if zone and zone.get('direction') in ('LONG','SHORT') else '观察方向未定'))
                    preparing=bool(observation and observation['mode']=='PREPARATION' and observation['status']=='AVAILABLE')
                    st.write('关键价格已识别 · 等待人工复核' if observation and observation['status']=='AVAILABLE' else '数据不完整：关键价格或距离基准尚未合资格')
                    st.write('ICT v0.3 · 独立历史观察')
                    st.caption(review_text(ict))
                    if decision:
                        st.write('当前阶段：'+DECISION_LABELS[decision['stage']])
                        st.write('下一条件：'+decision['next_condition'])
                        st.caption('下一观察区域：'+str(decision['next_region'] or '资料不足')+' · 期限：'+str(decision['until'] or '等待合格起点'))
                        st.caption('结构失效价：'+str(decision['invalid'] or '未知')+' · '+decision['invalid_condition'])
                        with st.expander('决策证据、缺项与人工动作'):
                            for evidence in decision['evidence']:
                                st.write('历史证据 '+evidence['id']+' · 发生 '+str(evidence['occurred_at'])+' · 确认 '+evidence['confirmed_at'])
                            st.write('尚缺资料：'+'；'.join(decision['missing']))
                            st.write('允许人工动作：'+'；'.join(decision['allowed']))
                            st.write('不应执行：'+'；'.join(decision['forbidden']))
                    st.checkbox('实时ICT自动提醒（默认关闭）',value=False,disabled=True,key='ict_live_alerts')
                    st.caption('真实RTH资格待验收，实时ICT自动提醒锁定关闭；历史事件不会写入实时提醒。')
                    if h['quality']!='AVAILABLE': st.caption('实时数据不合格 · 实时入场审查关闭')
                    st.caption('历史结构识别与现价距离独立；历史价格不生成实时入场建议。')
                    if focus:
                        st.write('当前关注：',focus.get('region_label',focus['key'])+f" {focus['low']:g}–{focus['high']:g}")
                        st.write('观察理由：',focus['reason'])
                        st.write('距离：',f"${focus['gap']:.2f} / {focus['atr_distance']:.3f} ATR · "+focus['distance_basis'])
                        st.write('下一动作：',focus['next_action'])
                        st.caption('行情时间 '+focus['quote_at']+' · 交易日 '+focus['trading_day'])
                    st.warning('准备下一交易时段计划；实时入场审查关闭。' if preparing else zh(('NO NEW ACTION · DATA_BLOCKED' if h['quality']!='AVAILABLE' else 'CANCEL SETUP' if state=='失效' else 'WAIT · 人工复核 SOP')))
                    st.write(TEXT['文案43'],f"{focus['low']}–{focus['high']}" if focus else f"{zone['low']}–{zone['high']}" if zone else '未形成')
                    st.write('人工候选入场区：',f"{plan['low']}–{plan['high']}" if plan else '未设定')
                    st.write('人工目标区：',f"{plan['target_low']}–{plan['target_high']}" if plan else '未设定')
                    st.write(TEXT['文案45'],(zone or {}).get('invalid') or '未知，资料不足')
                    rr=risk_reward(plan)
                    st.write('人工计划风险回报比：',f'{rr:.2f}' if rr is not None else '未设定')
                    st.write('人工备注：',store.note(selected) or '未填写')
                    with st.expander(TEXT['SOP详情']):
                        st.caption(zh(reason))
                        st.caption(TEXT['文案46'])
                        st.caption(TEXT['RR说明'])
                        st.caption(TEXT['备注说明'])
                        st.write(TEXT['文案48'])
                        st.markdown('  \n'.join(['□ 关键价格：'+('已识别，等待人工复核' if observation and observation['status']=='AVAILABLE' else '数据不完整'), '□ 市场结构转变（MSS）/ Sweep / FVG / CE：仅按1H已完成证据作独立历史观察', '□ 实时ICT提醒：关闭，真实盘中资格待验收', '□ 风险审查：等待人工复核', '□ 人工交易计划：'+('已保存，等待人工复核' if plan else '未设定')]))
                    if h['quality']!='AVAILABLE':st.caption('当前原始报价未通过实时检查，历史观察可独立使用。' if preparing else zh(h['reason']))
                    st.caption(f'评估 {now.isoformat()} · 原 ICT 观察规则不变 · 未完成条件标为正在形成，不作已确认')
                with st.container(key='alerts',border=True), panel('提醒'):
                    st.subheader('最新事件提醒 · '+selected[3:])
                    events=store.table('market_events'); read=store.acknowledged()
                    with st.expander('系统健康诊断（独立事件）'):
                        systems=store.table('system_events')
                        if not systems.empty: st.dataframe(systems[systems.kind.isin(['DATA_HEALTH','SYSTEM_HEALTH'])].head(10)[['at','symbol','reason']],hide_index=True)
                    if events.empty: st.caption(TEXT['文案56'])
                    else:
                        events=events[events.symbol==selected].head(6)
                        for row in events.itertuples():
                            st.write(f"{pd.Timestamp(row.at).tz_convert('America/New_York')} · {row.symbol} · {zh(row.kind)}")
                            st.caption(zh(row.reason)+' · 下一步：等待复核')
                            try:payload=json.loads(row.payload or '{}')
                            except (ValueError,TypeError):payload={}
                            event_zone=payload.get('zone') or (payload if 'low' in payload else None)
                            if isinstance(event_zone,dict):
                                st.caption(f"价格区 {event_zone.get('low','未设定')}–{event_zone.get('high','未设定')} · 失效 {event_zone.get('invalid','未设定')} · 目标 {event_zone.get('target_low','未设定')}–{event_zone.get('target_high','未设定')}")
                            else: st.caption('关键价格：'+str(payload.get('price','资料不足')))
                            if payload.get('quote_at'): st.caption('行情时间：'+str(payload['quote_at'])+' · 参数版本：'+str(payload.get('parameter_version','既有人工计划版本')))
                            if payload.get('plan_id'): st.caption('关联计划：'+payload['plan_id']+' · 第'+str(payload.get('plan_version'))+'版')
                            if row.id in read: st.caption(TEXT['文案58'])
                            elif st.button(TEXT['文案59'],key=f'ack_{row.id}'):
                                store.acknowledge(row.id); st.rerun(scope='fragment')
        if initializing and not getattr(market_data,'loading',lambda:False)():
            st.rerun()
    body()
    with panel('备注与计划编辑'):
        editors(store,codes)
