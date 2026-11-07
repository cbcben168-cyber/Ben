"""Small Chinese controls for historical experiments."""
from dataclasses import asdict
import os
from pathlib import Path
import sqlite3

import pandas as pd
import streamlit as st

from .experiment import BASELINE, Experiment, ExperimentStore, replay_cutoff

FIELDS = (
    ('ema_short', 'EMA短期周期', 5, 30, 1, '越小越快反映近期价格变化。'),
    ('ema_long', 'EMA长期周期', 35, 50, 1, '用于比较较长时间的价格方向。'),
    ('atr_period', 'ATR计算周期', 7, 20, 1, '衡量最近若干根K线的平均价格波动。'),
    ('sideways_atr', '横盘EMA距离阈值', .10, 1.50, .05, '越大，越容易把两条均线接近视为横盘；仍需满足高低点条件。'),
    ('candidate_atr', '候选关键价距离', .05, 1., .05, '越大，历史观察允许离关键价更远；不产生交易许可。'),
)
LABELS = {key: label for key, label, *_ in FIELDS}


def experiment_store():
    root = Path(__file__).resolve().parents[1]
    return ExperimentStore(os.environ.get('ICT_EXPERIMENT_DB', str(root/'data/v044/experiments.sqlite3')))


def apply_config(config):
    for key, value in asdict(config).items():
        st.session_state['experiment_' + key] = value


def controls(selected, data, wall_asof):
    """Widgets run in the home fragment: changing a factor never reloads market data."""
    store = experiment_store()
    for key, value in asdict(BASELINE).items():
        st.session_state.setdefault('experiment_' + key, value)
    # Keep the entry compact; the chart and right action card retain their columns.
    panel = st.expander('调整分析因子 · v0.4.4', expanded=False)
    with panel:
        st.caption(f'{selected[3:]} · 独立历史实验 · 拉动后自动重算')
        mode_col, date_col, period_col, preset_col = st.columns(4)
        mode = mode_col.selectbox('数据模式', ['最新已保存数据', '历史回放'], key='experiment_mode')
        # Only existing archive session labels are selectable; never fetch missing days.
        dates = {d for d in data.get('_archive_dates', []) if d <= wall_asof.date()}
        date_keys = ('daily', 'independent_daily') if not data['daily'].empty else ('minute', 'independent_daily')
        for key in date_keys:
            frame = data.get(key, pd.DataFrame())
            if not frame.empty:
                dates.update(d for d in frame.ts.dt.date if d <= wall_asof.date())
        dates = sorted(dates, reverse=True) or [wall_asof.date()]
        if st.session_state.get('experiment_day') not in dates:
            st.session_state['experiment_day'] = dates[0]
        day = date_col.selectbox('历史交易日期（纽约）', dates, format_func=lambda d:d.isoformat(),
                                 disabled=mode != '历史回放', key='experiment_day')
        period = period_col.selectbox('数据周期', ['日K', '1小时'], key='experiment_period')
        try:
            names = store.names()
        except (sqlite3.Error, OSError):
            names = ['Baseline']
            st.error('实验组合暂时无法读取，请检查实验数据库；原始参数仍可使用。')
        preset_col.selectbox('参数组合', names, key='experiment_preset')
        source = '原历史档案'
        if data.get('independent_coverage'):
            source = st.radio('日K来源（分开计算）', ['原历史档案', '独立更新档案'], horizontal=True,
                              key='experiment_source')
        columns = st.columns(2)
        for index, (key, label, low, high, step, help_text) in enumerate(FIELDS):
            with columns[index % 2]:
                st.slider(label, low, high, step=step, key='experiment_' + key, help=help_text)
                st.caption(help_text)
        config = Experiment(**{key: st.session_state['experiment_' + key] for key in asdict(BASELINE)})
        a, b, c, d = st.columns([2, 1, 1, 1])
        a.text_input('实验组合名称', placeholder='例如：短期敏感观察', key='experiment_name')
        def save():
            try:
                values = {key: st.session_state['experiment_' + key] for key in asdict(BASELINE)}
                store.save(st.session_state['experiment_name'], Experiment(**values))
                st.session_state['experiment_notice'] = '实验组合已保存，重新打开仍可载入。'
            except ValueError as exc:
                st.session_state['experiment_error'] = str(exc)
            except (sqlite3.Error, OSError):
                st.session_state['experiment_error'] = '实验组合保存失败，请检查实验数据库的可写状态。'
        b.button('保存组合', on_click=save, width='stretch')
        def load():
            try:
                apply_config(store.load(st.session_state['experiment_preset']))
                st.session_state['experiment_notice'] = '已载入参数组合。'
            except ValueError as exc:
                st.session_state['experiment_notice'] = str(exc)
            except (sqlite3.Error, OSError):
                st.session_state['experiment_notice'] = '实验组合暂时无法载入，请检查实验数据库。'
        c.button('载入组合', on_click=load, width='stretch')
        d.button('恢复默认', on_click=apply_config, args=(BASELINE,), width='stretch')
        if notice := st.session_state.pop('experiment_notice', None):
            st.success(notice)
        if error := st.session_state.pop('experiment_error', None):
            st.error(error)
        st.caption('Baseline为固定默认参数，不能覆盖。实时行情尚未通过验收。')
        comparison = st.container()
    # Date/mode changes refresh all legacy evidence too; factor-only changes stay
    # inside this fragment and reuse the loaded snapshots and fixed ICT results.
    contract = (mode, day, period, source)
    previous = st.session_state.get('_experiment_data_contract', contract)
    st.session_state['_experiment_data_contract'] = contract
    if previous != contract:
        st.rerun()
    try:
        asof = replay_cutoff(day) if mode == '历史回放' else wall_asof
        if asof > wall_asof:
            raise ValueError('所选交易日尚未完成收盘及2分钟确认，请选择更早日期。')
    except ValueError as exc:
        st.warning(str(exc))
        return config, None, period, source, comparison, mode
    return config, asof, period, source, comparison, mode


def comparison_view(container, baseline, experiment, before, after, config):
    def display(value):
        return '资料不足' if value == 'UNKNOWN' or value is None else value
    changed = [f'{LABELS[k]}：{asdict(BASELINE)[k]:g} → {v:g}' for k, v in asdict(config).items()
               if v != asdict(BASELINE)[k]]
    judgments = [('趋势', baseline['trend'], experiment['trend']),
                 ('波动分类', baseline['volatility'], experiment['volatility']),
                 ('候选距离资格', before['label'], after['label'])]
    with container:
        st.markdown('**原始参数与实验参数对比**')
        st.table(pd.DataFrame([{'判断': name, '原始参数': display(a), '实验参数': display(b),
                               '变化': '→ 不变' if a == b else '↗ 已变化'} for name, a, b in judgments]))
        details = [('短期EMA', baseline.get('ema20'), experiment.get('ema20')),
                   ('长期EMA', baseline.get('ema50'), experiment.get('ema50')),
                   ('ATR', baseline.get('atr14'), experiment.get('atr14')),
                   ('横盘阈值余量（ATR）', baseline.get('sideways_margin'), experiment.get('sideways_margin')),
                   ('关键价距离（ATR）', before.get('distance'), after.get('distance')),
                   ('允许距离（ATR）', before['threshold'], after['threshold'])]
        st.table(pd.DataFrame([{'数值': name, '原始': '资料不足' if a is None else f'{a:.6f}',
                               '实验': '资料不足' if b is None else f'{b:.6f}',
                               '变化值': '—' if a is None or b is None else f'{b-a:+.6f}'} for name, a, b in details]))
        if changed:
            st.caption('已改变：' + '；'.join(changed))
            if all(a == b for _, a, b in judgments):
                st.info('参数已改变，当前判断不变。')
            else:
                st.success('判断发生变化：' + '、'.join(name for name, a, b in judgments if a != b))
        else:
            st.caption('当前使用默认参数，与Baseline一致。')
        st.caption(f"数据截至 {experiment['at'] or '暂无'} · 可用 {experiment['bars']} 根 · 计算样本 {experiment['sample_bars']} 根")
        if experiment['trend'] == 'UNKNOWN':
            st.warning('资料不足：' + experiment['reason'])
        st.caption('候选距离：' + after['reason'])
