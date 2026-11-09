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
.st-key-focus-grid{display:grid!important;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}
.st-key-focus-grid>div{min-width:0}
.dash-candidate{min-height:195px;padding:10px}
.dash-candidate h4{margin-bottom:4px}
.dash-candidate p{font-size:13px;line-height:1.35;margin:5px 0}
.dash-periods{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:8px}
.dash-period{font-size:12px;line-height:1.4;overflow-wrap:anywhere}
.dash-candidate .dash-periods{grid-template-columns:1fr;gap:4px}
.dash-period[data-status="STALE"],.dash-period[data-status="REJECTED"]{color:#ffabb2}
.dash-scale{font-size:12px;color:#ffd18a;line-height:1.4;margin-top:6px}
.dash-summary{padding:10px 16px}
.dash-facts{grid-template-columns:repeat(6,minmax(0,1fr));margin-top:8px;gap:8px}
.dash-summary .dash-value{font-size:14px}.dash-summary .dash-label{font-size:12px}
.dash-summary .dash-foot{margin-top:6px;font-size:12px}
.dash-action{padding:12px 16px}.dash-action h3{font-size:20px}
.dash-action h4{font-size:17px;margin:10px 0 4px}
.dash-action p{font-size:13px;margin:5px 0}.dash-action .dash-label{font-size:11px;overflow-wrap:anywhere}
.dash-action .dash-rung{min-height:24px;font-size:14px}
.dash-action h4.historical-label{color:#81c8ff}.dash-action h4.manual-label{color:#ffd18a}
.dash-action h4.qualified-label{color:#ffabb2}
@media(max-aspect-ratio:1/1){.st-key-focus-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.dash-facts{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:850px){.st-key-focus-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:500px){.st-key-focus-grid{grid-template-columns:1fr}}
@media(max-width:1600px){.dash-summary,.dash-action{padding:14px}.dash-facts{gap:10px}.dash-value{font-size:16px}}
@media(max-width:700px){.dash-facts{grid-template-columns:1fr}.dash-heading{flex-wrap:wrap}}
</style>"""


def price(value):
    if value is None:
        return '暂无'
    text = str(value)
    return text[:-2] if text.endswith('.0') else text


def period_details(periods):
    if not periods:
        return ''
    rows = []
    for key in ('daily', 'hourly'):
        item = periods[key]
        rows.append(f'<div class="dash-period" data-period="{key}" data-status="{item["status"]}">'
                    f'<b>{item["label"]}最后完成：{escape(item["completed_text"])}</b> · 收盘 {price(item["close"])}<br>'
                    f'{item["label"]}来源：{escape(item["source"])} · 复权估值日：{escape(item["valuation_date"])}<br>'
                    f'{escape(item["description"])}'+
                    (f' · {escape(item["reason"])}' if item['reason'] else '')+'</div>')
    return ('<div class="dash-periods">'+''.join(rows)+'</div>'+
            (f'<div class="dash-scale">{escape(periods["scale_notice"])}</div>' if periods['scale_notice'] else ''))


def summary(symbol, state, stale, missing, at, historical, periods=None):
    trend = {'上涨': '↑ 偏多', '下跌': '↓ 偏空', '横盘': '↔ 横盘', '过渡': '↔ 过渡'}.get(state['trend'], '? 无法判断')
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
                f'{"历史时点回顾" if historical else "最新可用历史收盘"} · 波动 {escape(str(state["volatility"]).replace("UNKNOWN","目前无法确定"))}</div>'
                f'{period_details(periods)}</section>',
                unsafe_allow_html=True)


def action(symbol, manual, plan, setup, stale, basis_blocked=False, price_refs=None, readiness=None):
    refs = price_refs or dict(levels=[], missing=['没有已验收历史参考价'])
    rows = ''.join(f'<div class="dash-rung"><span>{escape(r["name"])}</span>'
                   f'<b>{price(r["low"])}–{price(r["high"])}</b></div>'
                   f'<div class="dash-label">{escape(r["from_date"][:10])} 至 {escape(r["to_date"][:10])}</div>'
                   for r in refs['levels']) or '<p>没有已验收历史参考价</p>'
    origin = refs['levels'][0] if refs['levels'] else {}
    basis = escape(str(origin.get('valuation_date') or '原始档案未标注'))
    source = escape(str(origin.get('source') or '来源待验收'))
    observed = escape(str(refs.get('asof', '未知')))
    manual_html = '<p>没有已保存人工计划</p>'
    if plan:
        values = [('入场区',f'{price(plan.get("low"))}–{price(plan.get("high"))}'),
                  ('失效／止损参考',price(plan.get('invalid'))),
                  ('用户目标1',price(plan.get('target_low'))),('用户目标2',price(plan.get('target_high')))]
        manual_html = ''.join(f'<div class="dash-rung dash-entry"><span>{name}</span><b>{escape(value)}</b></div>' for name,value in values)
        manual_html += ('<div class="dash-label">原始来源 USER_MANUAL · 版本 '+escape(str(plan.get('version','未知')))
                        +' · 保存 '+escape(str(plan.get('updated_at','未知')))
                        +' · 方向 '+escape(str(plan.get('direction','未知')))+'</div>')
        manual_html += '<p>保留原价；独立人工计划，非系统实时建议。</p>'
        if basis_blocked:
            manual_html += '<p>复权价格尺度未核实，暂停叠加与风险回报计算。</p>'
    missing = (readiness or {}).get('missing', ['入场、失效、方向、有效时间及价格尺度核验'])
    st.markdown(f'<section class="dash-action" aria-label="{escape(symbol)} 现在该怎么做">'
                f'<div class="dash-heading"><h3>{escape(symbol)}｜价格观察与行动</h3>'
                '<span class="dash-badge dash-red">实时资格关闭</span></div>'
                '<h4 class="historical-label">历史参考价格</h4><p>历史高低价供观察，不是盈利目标或入场指令。</p>'
                f'{rows}<div class="dash-label">{source} · 复权估值日 {basis}<br>参考时点 {observed}</div>'
                '<h4 class="manual-label">用户人工计划 · 原价</h4>'+manual_html+
                '<h4 class="qualified-label">合格交易目标 · 未具备条件</h4>'
                '<p>缺少：'+escape('、'.join(missing))+'</p>'
                '<div class="dash-foot">不自动生成目标1、目标2或止损价。实时ICT资格继续关闭。</div></section>',
                unsafe_allow_html=True)


def candidate(symbol, status, region, next_step, data_at=None, historical_trend=None,
              volatility=None, hourly_trend=None, close=None, source=None, data_status=None, periods=None):
    hourly_label = '1H历史趋势（已过期）' if periods and periods['hourly']['stale'] else '1H历史趋势'
    detail = period_details(periods) if periods else f'<p class="dash-label">历史截至 {escape(data_at or "暂无资料")}</p>'
    st.markdown(f'<article class="dash-candidate" aria-label="{escape(symbol)} 历史观察卡"><h4>{escape(symbol)}</h4>'
                f'{detail}'
                f'<p>日K {escape(historical_trend or "资料不足")} · 波动 {escape(str(volatility or "资料不足").replace("UNKNOWN","资料不足"))}'
                f' / {hourly_label} {escape(str(hourly_trend or "未验收").replace("UNKNOWN","未验收或不足"))}</p>'
                f'<p>最近收盘 <b>{price(close)}</b> · <span class="dash-label">{escape(source or "来源未知")}</span></p>'
                f'<p>历史区域 {escape(region)}</p><p class="dash-label">{escape(data_status or status)}</p></article>',
                unsafe_allow_html=True)
