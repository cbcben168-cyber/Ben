"""Compact presentation components. Prices and eligibility come from existing models."""
from html import escape

import streamlit as st


CSS = """<style>
.block-container{padding:3.4rem 1.2rem 1rem!important;max-width:none}
.st-key-answer-chart,.st-key-answer-action{min-width:0}
.st-key-answer-chart h3{font-size:20px;margin:0}
.dash-summary,.dash-action,.dash-candidate{background:#142036;border:1px solid #31415b;border-radius:14px;padding:18px;color:#ecf2fc}
.dash-summary{margin:0 0 12px;border-left:5px solid #f0838c}
.dash-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}
.dash-heading h2,.dash-action h3{margin:0;font-size:23px;color:#f2f6ff}
.dash-badge{display:inline-block;padding:4px 10px;border-radius:20px;font-size:14px;font-weight:650}
.dash-red{background:#512c3b;color:#ffb3ba}.dash-gray{background:#303e53;color:#d2d9e4}
.dash-yellow{background:#4c4025;color:#ffe0a0}.dash-green{background:#214738;color:#9ee2c1}
.dash-facts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:14px}
.dash-label{font-size:14px;color:#acbed5}.dash-value{font-size:18px;margin-top:3px;font-weight:600}
.dash-foot{font-size:14px;color:#bfd0e7;line-height:1.5;margin-top:12px}
.dash-action h4{font-size:24px;line-height:1.3;color:#ffb3ba;margin:12px 0 6px}
.dash-action p{font-size:15px;line-height:1.5;margin:8px 0}
.dash-ladder{margin-top:12px;border-left:2px solid #5a7093;padding-left:12px}
.dash-rung{display:flex;justify-content:space-between;align-items:center;gap:10px;min-height:35px;border-bottom:1px solid #30415b}
.dash-rung b{font-variant-numeric:tabular-nums}
.dash-target{color:#8de1bb}.dash-entry{color:#ffdc8b}.dash-stop{color:#ffabb2}
.dash-bars{display:grid;grid-template-columns:42px 1fr 42px;gap:6px;align-items:center;font-size:13px;margin-top:10px}
.dash-track{background:#23324a;height:10px;border-radius:8px;overflow:hidden}.dash-bar{height:10px;border-radius:8px}
.dash-candidate{min-height:140px;padding:14px}
.dash-candidate h4{font-size:20px;margin:0 0 10px}
.dash-candidate p{font-size:14px;line-height:1.5;margin:8px 0 0}
@media(max-width:1600px){.dash-summary,.dash-action{padding:14px}.dash-facts{gap:10px}.dash-value{font-size:16px}}
@media(max-width:700px){.dash-facts{grid-template-columns:1fr}.dash-heading{flex-wrap:wrap}}
</style>"""


def price(value):
    return '暂无' if value is None else f'{value:g}'


def summary(symbol, state, stale, missing, at, historical):
    trend = {'上涨': '↑ 偏多', '下跌': '↓ 偏空', '横盘': '↔ 横盘'}.get(state['trend'], '? 无法判断')
    current = '? 无法判断' if stale or missing else trend
    conclusion = '数据太旧不能判断' if stale else '目前无法确定' if missing else '继续等待'
    reason = '现在不能根据这份旧数据直接买卖' if stale else '资料不足，暂时不能判断买卖点' if missing else '实时审查尚未开放，等待合格数据和结构'
    fields = [('1 · 市场状态', current), ('2 · 当前结论', conclusion), ('3 · 原因', reason),
              ('4 · 最近有效数据', at), ('5 · 当前可否给出买卖点', '不能 · 暂无合格买卖点'),
              ('6 · 下一步动作', '先取得新行情，再复核条件')]
    facts = ''.join(f'<div><div class="dash-label">{escape(k)}</div><div class="dash-value">{escape(v)}</div></div>' for k,v in fields)
    st.markdown(f'<section class="dash-summary" aria-label="{escape(symbol)} 现在怎么看">'
                f'<div class="dash-heading"><h2>{escape(symbol)}｜现在怎么看</h2>'
                '<span class="dash-badge dash-red">● 暂停买卖判断</span></div>'
                f'<div class="dash-facts">{facts}</div>'
                f'<div class="dash-foot">旧资料趋势 {escape(trend)} · '
                f'{"历史时点回顾" if historical else "最新可用历史收盘"} · 波动 {escape(str(state["volatility"]).replace("UNKNOWN","目前无法确定"))}</div></section>',
                unsafe_allow_html=True)


def action(symbol, manual, plan, setup, stale):
    reason = '行情太旧，暂时不能判断今天买卖点' if stale else '当前实时审查条件尚未满足'
    values = [('目标2', None, 'target'), ('目标1', None, 'target'),
              ('观察区', None, 'entry'), ('失效／止损参考', None, 'stop')]
    origin = '暂无合格买卖点'
    if manual:
        is_test = '测试' in plan.get('memo','') or 'test' in (plan.get('memo','')+' '+plan['strategy_version']).lower()
        origin = ('测试用途 · ' if is_test else '') + '这是你保存的计划，不是系统实时建议'
        values = [('目标2', manual['target2'], 'target'), ('目标1', manual['target1'], 'target'),
                  ('观察区', f'{price(plan["low"])}–{price(plan["high"])}', 'entry'),
                  ('失效／止损参考', plan['invalid'], 'stop')]
    elif setup:
        origin = '以前的条件化计划 · 仅供历史复核'
        values[2] = ('观察区', f'{price(setup["low"])}–{price(setup["high"])}', 'entry')
        values[3] = ('失效／止损参考', setup['invalid'], 'stop')
    ladder = ''.join(f'<div class="dash-rung dash-{color}"><span>{name}</span><b>{escape(value if isinstance(value,str) else price(value))}</b></div>' for name,value,color in values)
    bars = '<p class="dash-label">收益／风险比例 · 暂无可计算数据</p>'
    if manual:
        scale = max(manual['risk'], manual['reward1'], manual['reward2'])
        bars = '<div class="dash-bars">'
        for label,value,color,ratio in [('风险',manual['risk'],'#f0838c','1'),
                                        ('目标1',manual['reward1'],'#69c9a3',f'{manual["rr1"]:.2f}'),
                                        ('目标2',manual['reward2'],'#78b3f5',f'{manual["rr2"]:.2f}')]:
            bars += f'<span>{label}</span><div class="dash-track"><div class="dash-bar" style="width:{value/scale*100:.2f}%;background:{color}"></div></div><b>{ratio}</b>'
        bars += '</div><div class="dash-foot">预计收益和承担风险的比例（未扣费用）</div>'
    html = (f'<section class="dash-action" aria-label="{escape(symbol)} 现在该怎么做"><div class="dash-heading">'
            f'<h3>{escape(symbol)}｜现在该怎么做</h3><span class="dash-badge dash-red">等待数据</span></div>'
            f'<h4>现在先不交易</h4><p>{reason}</p><p><span class="dash-badge dash-yellow">仅供复核</span> {escape(origin)}</p>'
            f'<div class="dash-ladder">{ladder}</div>{bars}'
            '<div class="dash-foot"><b>下一步</b>　先取得新行情，再复核计划与价格。</div></section>')
    st.markdown(html, unsafe_allow_html=True)


def candidate(symbol, status, region, next_step):
    st.markdown(f'<article class="dash-candidate"><h4>{escape(symbol)}</h4>'
                f'<span class="dash-badge dash-red">{escape(status)}</span>'
                f'<p>观察区　{escape(region)}</p><p>下一步　{escape(next_step)}</p></article>',
                unsafe_allow_html=True)
