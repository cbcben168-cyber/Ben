"""User-fixed ORB10/3R exploratory Train study, independent of frozen baselines."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .data import schedule, ohlcv_valid
from .storage import digest, normalized, write_csv, write_json, atomic

RULE=dict(version='orb10_3r_v1',range_minutes=10,signal_close_cutoff_et='10:30',
          cutoff_inclusive=False,stop_width_fraction=.25,target_r=3.,max_trades_per_day=1,
          cost_bps=2.,cost_probes=[0,2,4,8],gap_stop='ACTUAL_OPEN',
          gap_target='LIMIT_TARGET_CONSERVATIVE',both_hit='STOP_FIRST',
          entry='NEXT_5M_OPEN',exit='STOP_TARGET_OR_RTH_CLOSE',
          seed=20261003,bootstrap_reps=10000,split='train',orders_enabled=False,
          classification='USER_FIXED_EXPLORATORY_AFTER_BASELINE_SEEN')


def trade_day(minute,five,day):
    """Complete session prerequisite; one first breakout, never retry a skipped entry."""
    date=str(day.name.date()); minute=minute.sort_values('ts_start_utc');five=five.sort_values('ts_start_utc')
    base=dict(session_date=date,status='NO_TRADE',reason='NO_BREAKOUT',direction=0)
    expected=pd.date_range(day.open,day.close-pd.Timedelta(minutes=1),freq='min')
    if not minute.ts_start_utc.reset_index(drop=True).equals(pd.Series(expected)) or not ohlcv_valid(minute).all():
        return dict(**base,quality='FAILED_SESSION',reason_override='MINUTE_QUALITY')
    opening=five[five.ts_start_utc.isin([day.open,day.open+pd.Timedelta(minutes=5)])]
    if len(opening)!=2 or not ohlcv_valid(opening).all():
        return dict(**base,quality='FAILED_SESSION',reason_override='OPENING_RANGE_MISSING')
    high=float(opening.high.max());low=float(opening.low.min());width=high-low
    base.update(or_high=high,or_low=low,or_width=width,quality='PASS')
    if width<=0: return dict(**base,reason_override='ZERO_RANGE')
    local=five.ts_end_utc.dt.tz_convert('America/New_York')
    cutoff=local.dt.hour*60+local.dt.minute<630
    eligible=five[(five.ts_start_utc>=day.open+pd.Timedelta(minutes=10))&cutoff]
    signal=eligible[(eligible.close>high)|(eligible.close<low)]
    if signal.empty: return base
    row=signal.iloc[0];direction=1 if row.close>high else -1
    entry_time=row.ts_end_utc
    base.update(direction=direction,signal_time=entry_time.isoformat())
    next_bar=five[five.ts_start_utc==entry_time]
    if next_bar.empty: return dict(**base,reason_override='NEXT_5M_MISSING')
    path=minute[minute.ts_start_utc>=entry_time]
    if path.empty or path.ts_start_utc.iloc[0]!=entry_time: return dict(**base,reason_override='NEXT_1M_MISSING')
    entry=float(next_bar.open.iloc[0])
    if entry!=float(path.open.iloc[0]): raise ValueError('ORB10_ENTRY_FREQUENCY_MISMATCH')
    stop=high-.25*width if direction==1 else low+.25*width
    risk=direction*(entry-stop)
    base.update(entry_time=entry_time.isoformat(),entry_price=entry,stop=stop,risk_price=risk)
    if risk<=0: return dict(**base,status_override='SKIPPED',reason_override='ENTRY_BEYOND_STOP')
    target=entry+direction*3*risk
    exit_price=float(path.close.iloc[-1]);exit_time=day.close;reason='RTH_CLOSE';ambiguous=False
    for bar in path.itertuples():
        if direction*(bar.open-stop)<=0:
            exit_price=float(bar.open);exit_time=bar.ts_start_utc;reason='GAP_STOP';break
        if direction*(bar.open-target)>=0:
            exit_price=target;exit_time=bar.ts_start_utc;reason='GAP_TARGET';break
        hit_stop=bar.low<=stop if direction==1 else bar.high>=stop
        hit_target=bar.high>=target if direction==1 else bar.low<=target
        if hit_stop or hit_target:
            ambiguous=bool(hit_stop and hit_target);exit_price=stop if hit_stop else target
            exit_time=bar.ts_end_utc;reason='STOP' if hit_stop else 'TARGET';break
    gross=direction*(exit_price/entry-1)*10000;risk_bps=risk/entry*10000
    return dict(**base,status_override='COMPLETE',reason_override=reason,target=target,
        exit_time=exit_time.isoformat(),exit_price=exit_price,gross_bps=gross,net_bps=gross-2,
        risk_bps=risk_bps,gross_r=gross/risk_bps,net_r=(gross-2)/risk_bps,both_hit=ambiguous)


def backtest(minute,five,calendar):
    minutes={d:g for d,g in minute.groupby('session_date')};fives={d:g for d,g in five.groupby('session_date')}
    rows=[]
    for _,day in calendar.iterrows():
        date=str(day.name.date())
        record=trade_day(minutes.get(date,minute.iloc[:0]),fives.get(date,five.iloc[:0]),day)
        record['status']=record.pop('status_override',record['status'])
        record['reason']=record.pop('reason_override',record['reason'])
        rows.append(record)
    return pd.DataFrame(rows)


def clustered_ci(daily,reps=10000,block=1,seed=20261003):
    """Calendar-date/block resampling; flat days retained, mean is per completed trade."""
    if not (daily.status=='COMPLETE').any():return [None,None]
    values=np.where(daily.status=='COMPLETE',daily.net_bps.fillna(0),0.)
    counts=(daily.status=='COMPLETE').astype(int).to_numpy();n=len(daily)
    rng=np.random.default_rng(seed);samples=[]
    for offset in range(0,reps,256):
        size=min(256,reps-offset)
        starts=rng.integers(0,n,size=(size,int(np.ceil(n/block))))
        draws=((starts[:,:,None]+np.arange(block))%n).reshape(size,-1)[:,:n]
        denominator=counts[draws].sum(axis=1);total=values[draws].sum(axis=1)
        samples.extend(np.divide(total,denominator,out=np.full(size,np.nan),where=denominator>0))
    valid=np.asarray(samples);valid=valid[np.isfinite(valid)]
    return np.quantile(valid,[.025,.975]).tolist() if len(valid)>=reps*.95 else [None,None]


def equity(daily):
    """Illustrative 1x daily notional, cash on no-trade days; not risk sizing."""
    returns=np.where(daily.status=='COMPLETE',daily.net_bps.fillna(0)/10000,0.)
    nav=np.cumprod(1+returns);peak=np.maximum.accumulate(np.r_[1.,nav])[1:]
    return nav,nav/peak-1


def study(root):
    folder=root/'artifacts/orb10_3r_v1/train';registry_path=root/'locks/orb10_3r_v1/registry.json'
    if folder.exists() or registry_path.exists(): raise ValueError('ORB10_RUN_ALREADY_REGISTERED_USE_SAVED_RESULTS')
    baseline=json.loads((root/'locks/baseline_v1/registry.json').read_text())
    dates=baseline['splits']['train']
    meta_path=root/'data/normalized/manifest.json'
    if digest(meta_path)!=baseline['data_manifest_sha256']: raise ValueError('REGISTERED_DATA_CHANGED')
    registration=dict(rule=RULE,registered_at_utc=pd.Timestamp.now(tz='UTC').isoformat(),
        train_dates=dates,baseline_registry_sha256=digest(root/'locks/baseline_v1/registry.json'),
        data_manifest_sha256=digest(meta_path),source_sha256=digest(Path(__file__)),
        no_parameter_search=True,holdouts_not_used=True,matched_controls_not_run=True)
    write_json(registry_path,registration) # before reading outcome-bearing prices
    minute,five,manifest=normalized(root)
    minute=minute[minute.session_date.isin(dates)].copy();five=five[five.session_date.isin(dates)].copy()
    assert set(minute.session_date)==set(dates) and set(five.session_date)==set(dates)
    calendar=schedule(dates[0],dates[-1]);calendar=calendar[calendar.index.strftime('%Y-%m-%d').isin(dates)]
    daily=backtest(minute,five,calendar)
    if (daily.quality!='PASS').any(): raise ValueError('ORB10_TRAIN_SESSION_FAILED_QUALITY')
    trades=daily[daily.status=='COMPLETE'].copy()
    if not trades.empty:
        daily['net_bps']=daily.net_bps.fillna(0)
    else: daily['net_bps']=0.;trades=pd.DataFrame(columns=['gross_bps','net_bps','net_r','both_hit','reason'])
    nav,dd=equity(daily);daily['illustrative_nav']=nav;daily['drawdown']=dd
    daily['quarter']=pd.to_datetime(daily.session_date).dt.to_period('Q').astype(str)
    quarters=daily.groupby('quarter').apply(lambda p:pd.Series(dict(sessions=len(p),trades=int((p.status=='COMPLETE').sum()),
        net_mean_bps=float(p.loc[p.status=='COMPLETE','net_bps'].mean()) if (p.status=='COMPLETE').any() else None,
        net_sum_bps=float(p.net_bps.sum()))),include_groups=False).reset_index()
    costs=pd.DataFrame([dict(cost_bps=c,net_mean_bps=float((trades.gross_bps-c).mean()) if len(trades) else None) for c in RULE['cost_probes']])
    top=trades.nlargest(5,'net_bps').session_date if len(trades) else []
    remaining=trades[~trades.session_date.isin(top)] if len(trades) else trades
    gross_gain=trades.net_bps.clip(lower=0).sum();gross_loss=-trades.net_bps.clip(upper=0).sum()
    first=minute.iloc[0];last=minute.iloc[-1]
    summary=dict(version=RULE['version'],classification=RULE['classification'],sessions=len(daily),trades=len(trades),
        skipped=int((daily.status=='SKIPPED').sum()),no_trade=int((daily.status=='NO_TRADE').sum()),
        net_mean_bps=float(trades.net_bps.mean()) if len(trades) else None,
        net_mean_r=float(trades.net_r.mean()) if len(trades) else None,
        median_net_r=float(trades.net_r.median()) if len(trades) else None,
        min_risk_bps=float(trades.risk_bps.min()) if len(trades) else None,
        win_rate=float((trades.net_bps>0).mean()) if len(trades) else None,
        target_rate=float(trades.reason.isin(['TARGET','GAP_TARGET']).mean()) if len(trades) else None,
        profit_factor=float(gross_gain/gross_loss) if gross_loss>0 else None,
        date_ci=clustered_ci(daily),block5_ci=clustered_ci(daily,block=5),
        remove_top5_mean_bps=float(remaining.net_bps.mean()) if len(remaining) else None,
        total_illustrative_return=float(nav[-1]-1),max_illustrative_drawdown=float(dd.min()),
        buy_hold_price_return=float(last.close/first.open-1),
        buy_hold_net_return=float(last.close/first.open-1)-2/10000,
        both_hit_stop_first_count=int(trades.both_hit.sum()) if len(trades) else 0,
        formal_data_gate=manifest['formal_data_gate'],decision='WEAK_EXPLORATORY',
        reason='FIXED_RULE_TRAIN_ONLY_NO_MATCHED_CONTROL_OR_HOLDOUT_CONFIRMATION',orders_enabled=False)
    if len(trades) and summary['net_mean_bps']<=0:
        summary.update(decision='NO_EDGE_TRAIN_SCREEN',reason='NONPOSITIVE_NET_EXPECTATION')
    write_csv(folder/'daily.csv',daily);write_csv(folder/'trades.csv',trades)
    write_csv(folder/'quarterly.csv',quarters);write_csv(folder/'costs.csv',costs)
    write_json(folder/'summary.json',summary)
    by_side=trades.groupby('direction').agg(trades=('net_bps','size'),net_mean_bps=('net_bps','mean'),net_mean_r=('net_r','mean')) if len(trades) else pd.DataFrame()
    write_csv(folder/'by_side.csv',by_side.reset_index())
    report='# 10-Min ORB + 3R — Train 固定规则测试\n\n用户固定规则，探索性研究，无参数优化、无订单。\n\n'
    report+='```json\n'+json.dumps(summary,ensure_ascii=False,indent=2)+'\n```\n\n'
    report+='季度与方向统计：\n\n```csv\n'+quarters.to_csv(index=False)+'\n'+by_side.to_csv()+'\n```\n\n'
    report+='R按实际下一5m开盘价到固定止损计算；同时触及止盈止损按止损先。信号截止10:30严格排除，最后可用收盘10:25；每天首次突破后跳过也不重试。未出场按实际常规收盘。2bps为往返佣金与滑点假设，非实测执行成本。\n\n'
    report+='净R含成本，目标成交毛3R，净值低于3R。NAV/回撤为每天1倍名义本金、非固定风险仓位的示意；回撤仅交易日终，不包含盘中浮亏、借券、融资或真实成交。Buy & Hold用同一Train首开至末收，含隔夜，成本2bps，持仓时间和风险不同，不能直接据收益判优。\n\n'
    report+='区间为未复权SPY；Buy & Hold为价格收益，不含分红。没有matched controls或多重检验确认；日期与5日block CI为探索性，不能据此KEEP。原数据formal gate仍false，Validation/OOS未打开。\n'
    atomic(folder/'report.md',report)
    write_json(folder/'run_manifest.json',dict(status='SUCCESS',registration_sha256=digest(registry_path),
        source_sha256=registration['source_sha256'],input_sha256=registration['data_manifest_sha256'],
        registered_at_utc=registration['registered_at_utc'],completed_at_utc=pd.Timestamp.now(tz='UTC').isoformat()))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,(ax,draw)=plt.subplots(2,1,figsize=(10,6),sharex=True)
    ts=pd.to_datetime(daily.session_date)
    ax.plot(ts,nav,label='ORB10 3R: illustrative 1x, cost 2bps')
    day_prices=minute.groupby('session_date').close.last().reindex(daily.session_date)
    ax.plot(ts,day_prices.to_numpy()/first.open-2/10000,label='SPY price buy & hold, overnight; no dividends')
    ax.set_title('Train only — exploratory, no broker fills');ax.legend(fontsize=8)
    draw.fill_between(ts,dd*100,0,color='red',alpha=.3);draw.set_ylabel('Illustrative DD %')
    fig.tight_layout();fig.savefig(folder/'equity.png',dpi=150);plt.close(fig)
    if digest(meta_path)!=registration['data_manifest_sha256']: raise ValueError('ORB10_INPUT_CHANGED_DURING_RUN')
    print(json.dumps(summary,ensure_ascii=False));return folder


def main(argv=None):
    parser=argparse.ArgumentParser(description='Fixed ORB10 3R Train-only diagnostic')
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2])
    args=parser.parse_args(argv)
    try:study(args.root.resolve());return 0
    except Exception as exc:
        message=str(exc);safe=message if message.isupper() and len(message)<100 else 'ORB10_RESEARCH_FAILED'
        failure=dict(status='FAILED',error=safe,error_type=type(exc).__name__)
        write_json(args.root.resolve()/'logs/orb10_3r_v1'/
                   (pd.Timestamp.now(tz='UTC').strftime('%Y%m%dT%H%M%S%fZ')+'.json'),failure)
        print(json.dumps(failure));return 1


if __name__=='__main__':raise SystemExit(main())
