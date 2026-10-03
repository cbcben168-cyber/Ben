"""Deterministic daily diagnostic review; proposals never change running rules."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
from .storage import atomic, write_csv, write_json, digest

OBS_COLUMNS=['event_id','session_date','setup','direction','signal_time','observed_at','entry_price','exit_time','exit_price','gross_bps','net_bps','mfe_bps','mae_bps','status','reason','price_basis']
EVENT_COLUMNS=['event_id','session_date','setup','direction','signal_time','available_at','status','reason']

def table(path,columns):
    return pd.read_csv(path).reindex(columns=columns) if Path(path).exists() else pd.DataFrame(columns=columns)

def mean_ci(frame,reps=10000):
    if frame.empty or frame.session_date.nunique()<2: return None,None,None
    groups=frame.groupby('session_date').net_bps.agg(['sum','count'])
    rng=np.random.default_rng(20261003); draws=rng.integers(0,len(groups),size=(reps,len(groups)))
    means=groups['sum'].to_numpy()[draws].sum(axis=1)/groups['count'].to_numpy()[draws].sum(axis=1)
    low,high=np.quantile(means,[.025,.975])
    return float(frame.net_bps.mean()),float(low),float(high)

def chart(path,minute,observations):
    if minute.empty: return
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    times=pd.to_datetime(minute.ts_start_utc,utc=True).dt.tz_convert('America/New_York')
    fig,axis=plt.subplots(figsize=(12,5))
    axis.plot(times,minute.close,label='SPY 1m',color='black',linewidth=.8)
    for n in [9,20,50]: axis.plot(times,minute.close.rolling(n,min_periods=n).mean(),label=f'MA{n}')
    for row in observations.itertuples():
        if pd.notna(row.entry_price): axis.scatter(pd.Timestamp(row.observed_at).tz_convert('America/New_York'),row.entry_price,marker='^',color='green')
        if pd.notna(row.exit_price): axis.scatter(pd.Timestamp(row.exit_time).tz_convert('America/New_York'),row.exit_price,marker='v',color='red')
    axis.set_title('Diagnostic observation only — no broker fills'); axis.set_ylabel('USD'); axis.legend()
    axis.xaxis.set_major_formatter(matplotlib.dates.DateFormatter('%H:%M',tz=times.dt.tz))
    axis.set_xlabel('America/New_York'); fig.tight_layout(); fig.savefig(path,dpi=140); plt.close(fig)

def daily(root,version,date,session_status='COMPLETE'):
    mode='replay' if version.startswith('replay_') else 'diagnostic-shadow'
    base=root/'artifacts/paper'/version
    day=base/date
    events=table(day/'events.csv',EVENT_COLUMNS)
    observations=table(day/'observations.csv',OBS_COLUMNS)
    operational=table(day/'operational.csv',['timestamp','status','reason'])
    complete=observations[observations.status=='COMPLETE']
    cumulative=[]
    for file in sorted(base.glob('*/observations.csv')):
        if file.parent.name<=date:
            part=pd.read_csv(file); cumulative.append(part[part.status=='COMPLETE'])
    all_complete=pd.concat(cumulative,ignore_index=True) if cumulative else pd.DataFrame(columns=OBS_COLUMNS)
    points=mean_ci(all_complete)
    inputs={p.name:digest(p) for p in [day/'events.csv',day/'observations.csv',day/'operational.csv',day/'bars.csv',day/'session_summary.json',day/'quotes.csv',day/'quotes.jsonl'] if p.exists()}
    cumulative_hash=hashlib.sha256(all_complete.to_csv(index=False).encode()).hexdigest()
    key=hashlib.sha256(json.dumps(dict(inputs=inputs,cumulative=cumulative_hash,status=session_status,generator_sha256=digest(Path(__file__))),sort_keys=True).encode()).hexdigest()
    prior=sorted(day.glob('review_*/review_manifest.json'))
    for manifest in prior:
        if json.loads(manifest.read_text())['idempotency_key']==key: return manifest.parent
    revision=len(prior)+1; folder=day/f'review_{revision:03d}'; folder.mkdir(parents=True,exist_ok=False)
    pending=observations[observations.status=='OPEN']
    valid_days=int(all_complete.session_date.nunique())
    complete_days=sum(1 for p in base.glob('*/session_summary.json') if p.parent.name<=date and json.loads(p.read_text()).get('canonical_bars_complete'))
    status='PARTIAL' if not pending.empty or session_status!='COMPLETE' else 'INSUFFICIENT' if valid_days<60 or len(all_complete)<100 else 'DIAGNOSTIC_ONLY'
    metrics=dict(session_date=date,version=version,mode=mode,report_revision=revision,
                 signals=len(events),observations=len(observations),completed_observations=len(complete),
                 executable_fills=0,net_mean_bps=float(complete.net_bps.mean()) if len(complete) else None,
                 mfe_bps_mean=float(complete.mfe_bps.mean()) if len(complete) and complete.mfe_bps.notna().any() else None,
                 mae_bps_mean=float(complete.mae_bps.mean()) if len(complete) and complete.mae_bps.notna().any() else None,
                 open_observations=len(pending),status=status,broker_position='NOT_CONNECTED',
                 price_basis='observed quote proxy, not executable NBBO',formal_data_gate=False)
    write_csv(folder/'daily_metrics.csv',pd.DataFrame([metrics]))
    cumulative_metrics=dict(version=version,mode=mode,completed_observations=len(all_complete),
        observed_sessions=valid_days,complete_bar_sessions=complete_days,net_mean_bps=points[0],ci_low_bps=points[1],ci_high_bps=points[2],seed=20261003,
        sample_status='INSUFFICIENT' if valid_days<60 or len(all_complete)<100 else 'DIAGNOSTIC_ONLY')
    write_csv(folder/'cumulative_metrics.csv',pd.DataFrame([cumulative_metrics]))
    proposal=f'{version}_{date}_r{revision}'
    options=[dict(proposal_id=proposal,option_id='A',parent_version=version,
                 hypothesis='保持冻结规则，继续收集未来样本',change_scope='无策略修改',
                 evidence=f'{len(all_complete)} observations / {valid_days} sessions',expected_effect='增加可判断证据，不保证盈利',
                 risk='现有数据/执行资格问题仍在',validation_plan='累计至少60session/100 observations；仍不代替正式资格认证',status='PROPOSED'),
             dict(proposal_id=proposal,option_id='B',parent_version=version,
                 hypothesis='先核验成交量与行情权限',change_scope='数据诊断与独立口径对账；不改信号',
                 evidence='formal_data_gate=False / quote execution remains unqualified',expected_effect='降低测量偏差',
                 risk='可能仍无法解释供应商差异',validation_plan='新日期复取、跨频率/实际quote对账；不得放宽阈值救策略',status='PROPOSED')]
    if not operational.empty and (operational.status!='OK').any():
        options.append(dict(proposal_id=proposal,option_id='C',parent_version=version,
            hypothesis='诊断数据延迟或恢复流程',change_scope='运行时质量控制，不改入场/TP/SL',
            evidence=f'{int((operational.status!="OK").sum())} non-OK runtime records',expected_effect='减少缺失/延迟事件',
            risk='需要新的未来运行证据验证',validation_plan='复现故障、测试恢复/去重后再在未来窗口比较',status='PROPOSED'))
    write_csv(folder/'optimization_options.csv',pd.DataFrame(options))
    decision_columns=['decision_id','proposal_id','option_id','parent_version','candidate_version','user_selection_at','user_approval_at','approved_scope','branch','commit','validation_run_ids','status','promotion_approval_at']
    write_csv(folder/'optimization_decisions.csv',pd.DataFrame([dict(proposal_id=proposal,parent_version=version,status='AWAITING_USER_CHOICE')],columns=decision_columns))
    lines=[f'# 每日 Forward 诊断复盘 — {date}',f'\n状态：{status}；版本：{version}；模式：{mode}；修订：{revision}',
        '\n历史重放，quote为合成收盘代理；不是未来样本。' if mode=='replay' else '\n未来实时quote代理观察。',
        '\n**仅观察信号和报价代理，无券商成交。累计事件重叠，不是可投资组合收益。**',
        f'\n当日信号 {len(events)}；完成观察 {len(complete)}；未完成 {len(pending)}；可执行成交 0。',
        f'\n累计 {valid_days} 个有完成观察的session、{len(all_complete)} 个观察；净均值/95%日期聚类CI：{points} bps。',
        f'\n完整分钟数据session：{complete_days}；当日quote路径MFE/MAE均值：{metrics["mfe_bps_mean"]}/{metrics["mae_bps_mean"]} bps。只有已接收到的quote代理参与，不推定未观察的价格路径。',
        '\n费用采用冻结的2bps额外保守假设；quote是已接收到的last-price代理，未核验NBBO新鲜度，不声称真实成交或收益。',
        '\n数据成交量资格尚未通过。单日结果不支持修改策略或TP/SL，正常波动与edge变化无法据此区分。',
        '\n## 优化选项（等待用户选择）']
    for option in options:
        lines.append(f'\n- {option["option_id"]}：{option["hypothesis"]}。范围：{option["change_scope"]}。依据：{option["evidence"]}。作用：{option["expected_effect"]}。风险：{option["risk"]}。验证：{option["validation_plan"]}。')
    lines.append('\n默认建议 A。选择和批准记录为AWAITING_USER_CHOICE；不会自动修改或替换运行版本。')
    atomic(folder/'daily_review.md','\n'.join(lines)+'\n')
    bars_path=day/'bars.csv'
    if bars_path.exists(): chart(folder/'entry_exit_ma.png',pd.read_csv(bars_path),observations)
    manifest=dict(version=version,date=date,mode=mode,revision=revision,idempotency_key=key,inputs=inputs,
                  cumulative_sha256=cumulative_hash,status=status,outputs={p.name:digest(p) for p in folder.iterdir() if p.is_file()})
    write_json(folder/'review_manifest.json',manifest)
    return folder
