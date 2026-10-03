"""Independent quote-only collector/report/watch; existing locks stay unchanged."""
import argparse
import json
import os
import time
from pathlib import Path
import pandas as pd
from .gamma import MODEL, levels, candidates
from .storage import atomic, write_csv, write_json, digest
from .data import schedule, normalize, ohlcv_valid, aggregate5_fast


def request(call, *args, **kwargs):
    from futu import RET_OK
    for attempt in range(3):
        ret, data = call(*args, **kwargs)
        if ret == RET_OK: return data
        if attempt<2: time.sleep(3.1*(attempt+1))
    raise RuntimeError('GAMMA_REQUEST_FAILED')


def collect(root, ctx, now=None):
    today=(now or pd.Timestamp.now(tz='UTC')).tz_convert('America/New_York').strftime('%Y-%m-%d')
    end=(pd.Timestamp(today)+pd.Timedelta(days=7)).strftime('%Y-%m-%d')
    # No strike/volume filtering: full declared expiry range or explicit failure.
    chain=request(ctx.get_option_chain,'US.SPY',start=today,end=end)
    if chain.empty or chain.code.duplicated().any(): raise ValueError('GAMMA_CHAIN_INVALID')
    codes=chain.code.tolist(); chunks=[]
    spot=request(ctx.get_market_snapshot,['US.SPY'])
    if len(spot)!=1 or spot.code.iloc[0]!='US.SPY': raise ValueError('GAMMA_SPOT_MISSING')
    for offset in range(0,len(codes),200):
        time.sleep(3.1)
        batch=request(ctx.get_market_snapshot,codes[offset:offset+200])
        chunks.append(batch)
    raw=pd.concat(chunks,ignore_index=True)
    asof=pd.Timestamp.now(tz='UTC')
    stamp=asof.strftime('%Y%m%dT%H%M%S%fZ')
    folder=root/'artifacts/gamma_levels_v1'/today/stamp
    write_csv(folder/'chain.csv',chain);write_csv(folder/'snapshot.csv',raw)
    write_csv(folder/'spot.csv',spot)
    write_json(folder/'manifest.json',dict(model=MODEL,captured_at_utc=asof.isoformat(),
        expected_codes=codes,chain_sha256=digest(folder/'chain.csv'),
        snapshot_sha256=digest(folder/'snapshot.csv'),spot_sha256=digest(folder/'spot.csv'),
        source_sha256=digest(Path(__file__).with_name('gamma.py')),
        collector_sha256=digest(Path(__file__)),date=today,orders_enabled=False))
    return folder


def analyze(folder):
    meta=json.loads((folder/'manifest.json').read_text())
    for name in ['chain','snapshot','spot']:
        if digest(folder/(name+'.csv'))!=meta[name+'_sha256']: raise ValueError('GAMMA_INPUT_HASH_MISMATCH')
    if meta['source_sha256']!=digest(Path(__file__).with_name('gamma.py')):
        raise ValueError('GAMMA_SOURCE_CHANGED_USE_NEW_VERSION')
    raw=pd.read_csv(folder/'snapshot.csv'); spot=pd.read_csv(folder/'spot.csv').iloc[0]
    spot_time=pd.Timestamp(spot.update_time).tz_localize('America/New_York').tz_convert('UTC')
    result,curve=levels(raw,spot.last_price,pd.Timestamp(meta['captured_at_utc']),spot_time,meta['expected_codes'])
    write_json(folder/'levels.json',dict(model=MODEL,levels=result))
    table=pd.DataFrame(result);table['roots']=table.roots.map(json.dumps)
    write_csv(folder/'levels.csv',table);write_csv(folder/'profile.csv',curve)
    return result


def report(day):
    """Daily inventory/fault review; never substitutes an option PnL or KEEP."""
    folders=sorted(p.parent for p in day.glob('*/levels.json'))
    issues=list(day.glob('failure_*.json'))
    report_lines=['# SPY Gamma 位置与每日诊断','',
        '模型假设：Call正、Put负；持仓量不是做市商净持仓。OI日期未知，正式资格未通过。',
        'BSM近似美国式SPY期权，r=q=0、固定各行权价IV；0DTE与7自然日分别报告。',
        '没有历史链回填、没有订单、没有自动修改现有冻结策略。','']
    if folders:
        folder=folders[-1];records=json.loads((folder/'levels.json').read_text())['levels']
        report_lines+=['|范围|Gamma 0|Call Wall|Put Wall|价格|状态|','|---|---:|---:|---:|---:|---|']
        for row in records:
            fmt=lambda x:'不可用' if x is None else f'{x:.2f}'
            report_lines.append(f"|{row['scope']}|{fmt(row['gamma_zero'])}|{fmt(row['call_wall'])}|{fmt(row['put_wall'])}|{row['spot']:.2f}|{row['status']}|")
        report_lines+=['','采集时间：'+records[0]['asof_utc'],
            f"整链预期{records[0]['expected_contracts']}份，收到{records[0]['snapshot_contracts']}份；不合格{records[0]['invalid_contracts']}份。旧报价与缺失/非法合约均阻止候选。",
            '零点搜索范围为当前价格±10%；所有零点保存在levels.json，显示最近零点；不保证范围外没有零点。',
            '旧报价或无完整链时，上述数字仅为演练估计，不生成有效候选。','']
        curve=pd.read_csv(folder/'profile.csv')
        if not curve.empty:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            fig,ax=plt.subplots(figsize=(10,5))
            for scope,part in curve.groupby('scope'): ax.plot(part.spot_price,part.net_gex/1e6,label=scope)
            ax.axhline(0,color='black',lw=.8);ax.axvline(records[0]['spot'],color='gray',ls='--',label='SPY snapshot')
            for row in records:
                for key,color in [('gamma_zero','purple'),('call_wall','red'),('put_wall','green')]:
                    if row.get(key) is not None: ax.axvline(row[key],color=color,ls=':',alpha=.5,label=row['scope']+' '+key)
            states=', '.join(r['scope']+': '+r['status'] for r in records)
            ax.set(title='SPY modeled gamma — diagnostic, OI date unknown\n'+states,xlabel='SPY hypothetical price',ylabel='Modeled USD GEX per 1% move (millions)')
            ax.legend(fontsize=7);fig.tight_layout();fig.savefig(day/'gamma_levels.png',dpi=150);plt.close(fig)
    all_signals=[]
    for folder in folders:
        path=folder/'candidates.csv'
        if path.exists() and path.stat().st_size>1:
            try: all_signals.append(pd.read_csv(path))
            except pd.errors.EmptyDataError: pass
    signals=pd.concat(all_signals,ignore_index=True).drop_duplicates(['scope','setup','signal_time']) if all_signals else pd.DataFrame()
    write_csv(day/'daily_candidates.csv',signals)
    choices=day/'optimization_choices.csv'
    if not choices.exists():
        write_csv(choices,pd.DataFrame([
            dict(option=key,description=desc,status='AWAITING_USER_CHOICE',version=MODEL['version'])
            for key,desc in [('A','Keep frozen and collect'),('B','Qualify OI dates and quotes'),
                             ('C','Preregister one new hypothesis after qualification')]]))
    report_lines+=['## 买卖点规则','',
        '- 正Gamma模型环境：Put Wall测试后收回上方观察做多；Call Wall测试后收回下方观察做空。',
        '- 突破Call Wall后回踩守住观察做多；跌破Put Wall后反抽不过观察做空。',
        '- Gamma 0穿越后回踩确认，分别观察向上收复和向下失守；零点上方不自动等于看多。',
        '- 信号用完整5m线；实际采集晚于信号时，候选入场时间不得早于检测后下一分钟。无实际后续价格不填成交价。',
        '- 失效参考为确认线低点/高点；有利方向的下一墙位只作目标参考；实际入场若越过失效位/目标则应取消。先固定30分钟、2bps成本，不执行TP/SL。',
        '- 采集首份完整新鲜快照冻结当日位置；其后更新仅供诊断，禁止移动水平制造穿越。','',
        f'当前累计候选记录：{len(signals)}；失败记录：{len(issues)}。没有实际成交或盈利证明。',
        '尚无历史期权链的独立回测，候选没有自动晋级；日报不计算虚构收益。','',
        '## 供用户选择的下一步','',
        'A. 保持模型和规则冻结，继续积累快照。',
        'B. 优先核实OI日期、报价更新含义、链覆盖和美国式定价误差。',
        'C. 数据资格通过且样本充足后，登记单一新增假设，独立验证。',
        '当前选择：等待用户；不会自动优化。']
    atomic(day/'daily_review.md','\n'.join(report_lines)+'\n')
    return day/'daily_review.md'


def cycle(root,ctx,with_bars=False):
    folder=collect(root,ctx); records=analyze(folder)
    day=folder.parent
    if with_bars:
        from futu import SubType,AuType
        request(ctx.subscribe,['US.SPY'],[SubType.K_1M],subscribe_push=False)
        raw=request(ctx.get_cur_kline,'US.SPY',1000,SubType.K_1M,AuType.NONE)
        now=pd.Timestamp.now(tz='UTC'); date=day.name
        bars=normalize(raw,semantics='end',minutes=1)
        bars=bars[(bars.session_date==date)&(bars.ts_end_utc<=now)].copy()
        if not bars.empty and not ohlcv_valid(bars).all(): raise ValueError('GAMMA_BARS_INVALID')
        # Only complete consecutive five-minute blocks; missing blocks never filled.
        groups=bars.groupby(bars.ts_start_utc.dt.floor('5min'))
        complete=[p for _,p in groups if len(p)==5 and p.ts_start_utc.sort_values().diff().dropna().eq(pd.Timedelta(minutes=1)).all()]
        if complete:
            five=aggregate5_fast(pd.concat(complete))
            frozen_path=day/'frozen_levels.json'
            if not frozen_path.exists() and any(r['status']=='DIAGNOSTIC_ONLY' for r in records):
                write_json(frozen_path,dict(available_at=pd.Timestamp.now(tz='UTC').isoformat(),levels=records))
            if frozen_path.exists():
                frozen=json.loads(frozen_path.read_text()); found=[]
                for row in frozen['levels']:
                    # Suppress signals when the CURRENT feed is stale/incomplete too.
                    current=next(r for r in records if r['scope']==row['scope'])
                    if current['status']=='DIAGNOSTIC_ONLY':
                        signals=candidates(five,row,frozen['available_at'],now)
                        if not signals.empty: found.append(signals)
                write_csv(folder/'candidates.csv',pd.concat(found,ignore_index=True) if found else pd.DataFrame())
    path=report(day)
    print(json.dumps(dict(status='DIAGNOSTIC',levels=records,report=str(path),orders_enabled=False)),flush=True)
    return folder


def main(argv=None):
    parser=argparse.ArgumentParser(description='Independent SPY gamma diagnostic; no orders')
    parser.add_argument('command',choices=['collect','report','watch'])
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument('--date');parser.add_argument('--folder',type=Path)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args(argv);ctx=None;owned_lock=False
    args.root=args.root.resolve()
    lock=args.root/'artifacts/gamma_levels_v1/runner.lock'
    try:
        if args.command=='report':
            if args.folder: analyze(args.folder); day=args.folder.parent
            elif args.date:
                if pd.Timestamp(args.date).strftime('%Y-%m-%d')!=args.date: parser.error('ISO date required')
                day=args.root/'artifacts/gamma_levels_v1'/args.date
            else: parser.error('--date or --folder required')
            print(report(day));return 0
        if args.command=='watch':
            lock.parent.mkdir(parents=True,exist_ok=True)
            try:
                fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
            except FileExistsError:
                print('GAMMA_RUNNER_ALREADY_LOCKED');return 1
            with os.fdopen(fd,'w') as stream: stream.write(str(os.getpid()))
            owned_lock=True
        from futu import OpenQuoteContext
        ctx=OpenQuoteContext(host=os.getenv('FUTU_HOST','127.0.0.1'),port=int(os.getenv('FUTU_PORT','11111')))
        while True:
            now=pd.Timestamp.now(tz='UTC');date=now.tz_convert('America/New_York').strftime('%Y-%m-%d')
            day=schedule(date,date)
            opened=not day.empty and day.iloc[0].open<=now<day.iloc[0].close
            if args.command=='collect' or opened:
                try: cycle(args.root,ctx,with_bars=args.command=='watch')
                except Exception as exc:
                    folder=args.root/'artifacts/gamma_levels_v1'/date
                    write_json(folder/('failure_'+now.strftime('%H%M%S%f')+'.json'),dict(error_type=type(exc).__name__,reason='GAMMA_COLLECTION_OR_ANALYSIS_FAILED',at_utc=now.isoformat(),orders_enabled=False))
                    report(folder);print('GAMMA_COLLECTION_OR_ANALYSIS_FAILED',flush=True)
                    if args.once or args.command=='collect': return 1
            else: print(json.dumps(dict(status='CLOSED',orders_enabled=False)),flush=True)
            if args.once or args.command=='collect': return 0
            time.sleep(30 if not opened else 300)
    except KeyboardInterrupt: return 0
    finally:
        if ctx is not None: ctx.close()
        if owned_lock: lock.unlink(missing_ok=True)


if __name__=='__main__': raise SystemExit(main())
