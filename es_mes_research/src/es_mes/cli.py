"""Opt-in research commands. Quotes only, no trade/account interfaces."""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path
import pandas as pd
from .core import SPECS,RULE,validate,run,hold_reference

ROOT=Path(__file__).resolve().parents[2]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    text=value if isinstance(value,str) else json.dumps(value,indent=2,allow_nan=False)
    temp.write_text(text,encoding='utf-8')
    for attempt in range(4):
        try:temp.replace(path);break
        except PermissionError:
            if attempt==3:raise
            time.sleep(.05*(attempt+1))


def selection(root):
    file=root/'state/selection.json'
    choice=json.loads(file.read_text())['choice'] if file.exists() else 'none'
    if choice not in ['none','ES','MES','both']:raise ValueError('SELECTION_INVALID')
    return ['ES','MES'] if choice=='both' else [] if choice=='none' else [choice]


def allowed(root,product):
    if product not in selection(root):raise ValueError('RESEARCH_DISABLED_SELECT_PRODUCT_FIRST')


def request(call,*args,**kwargs):
    from futu import RET_OK
    for attempt in range(3):
        result=call(*args,**kwargs)
        if result[0]==RET_OK:return result[1:]
        message=str(result[1]).lower()
        if any(x in message for x in ['权限','未开通','permission','no authority','no right']):
            raise ValueError('FUTURES_PERMISSION_DENIED')
        if attempt<2:time.sleep(3.1*(attempt+1))
    raise ValueError('FUTURES_REQUEST_FAILED')


def context():
    from futu import OpenQuoteContext
    return OpenQuoteContext(host=os.getenv('FUTU_HOST','127.0.0.1'),port=int(os.getenv('FUTU_PORT','11111')))


def probe(root):
    from futu import Market,SecurityType,KLType,AuType
    ctx=context();result=dict(at_utc=pd.Timestamp.now(tz='UTC').isoformat(),orders_enabled=False,products={})
    try:
        catalog=request(ctx.get_stock_basicinfo,Market.US,SecurityType.FUTURE)[0]
        for product in SPECS:
            codes=catalog.loc[catalog.code.str.fullmatch('US\.'+product+r'\d{4}'),'code'].sort_values()
            item=dict(catalog_contracts=int(len(codes)),snapshot=False,history=False)
            if len(codes):
                code=codes.iloc[0];item['sample_contract']=code
                try:request(ctx.get_market_snapshot,[code]);item['snapshot']=True
                except ValueError as exc:item['snapshot_error']=str(exc)
                time.sleep(3.1)
                # Last completed cash date, no request for future market data.
                today=pd.Timestamp.now(tz='America/New_York').normalize()
                from .core import calendar
                days=calendar((today-pd.Timedelta(days=10)).strftime('%Y-%m-%d'),(today-pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
                date=days.index[-1].strftime('%Y-%m-%d')
                try:
                    frame,_=request(ctx.request_history_kline,code,start=date,end=date,ktype=KLType.K_1M,autype=AuType.NONE,max_count=1)
                    item.update(history=not frame.empty,history_sample_rows=len(frame),probe_date=date)
                except ValueError as exc:item['history_error']=str(exc)
            result['products'][product]=item
    finally:ctx.close()
    save(root/'artifacts/probe.json',result);return result


def import_data(root,product,raw,roll,start,end,source):
    folder=root/'data'/product
    if (folder/'manifest.json').exists():raise ValueError('DATASET_ALREADY_REGISTERED_NO_OVERWRITE')
    frame,cal=validate(raw,roll,product,start,end)
    dates=cal.index.strftime('%Y-%m-%d').tolist();n=len(dates);a=int(n*.6);b=int(n*.8)
    splits=dict(train=dates[:a],validation=dates[a+1:b],locked_oos=dates[b+1:],embargo=[dates[a],dates[b]]) if n>=500 else dict(train=dates,validation=[],locked_oos=[],embargo=[])
    save(folder/'minute.csv',frame.to_csv(index=False));save(folder/'roll_map.csv',roll.to_csv(index=False))
    save(folder/'manifest.json',dict(product=product,source=source,start=start,end=end,sessions=n,
        schema='UTC_START_UNADJUSTED_EXPLICIT_CONTRACTS',spec=SPECS[product],rule=RULE,
        splits=splits,formal_split_eligible=n>=500,formal_data_gate=False,
        provenance='SOURCE_TIMESTAMPS_EXPIRY_USER_DECLARED_REQUIRES_QUALIFICATION',
        minute_sha256=sha(folder/'minute.csv'),roll_sha256=sha(folder/'roll_map.csv'),
        source_sha256=sha(Path(__file__).with_name('core.py')),
        registered_at_utc=pd.Timestamp.now(tz='UTC').isoformat(),orders_enabled=False))
    save(folder/'manifest.sha256',sha(folder/'manifest.json'))
    return dict(status='DIAGNOSTIC_DATA_REGISTERED',product=product,sessions=n,formal_split_eligible=n>=500)


def collect(args):
    from futu import KLType,AuType
    from .core import contract_ok
    if not contract_ok(args.contract,args.product):raise ValueError('EXPLICIT_CONTRACT_REQUIRED')
    if (args.root/'data'/args.product/'manifest.json').exists():raise ValueError('DATASET_ALREADY_REGISTERED_NO_OVERWRITE')
    ctx=context();pages=[];token=None;tokens=set();last_keys=set()
    try:
        for page in range(1000):
            frame,next_token=request(ctx.request_history_kline,args.contract,start=args.start,end=args.end,
                ktype=KLType.K_1M,autype=AuType.NONE,max_count=1000,page_req_key=token)
            keys=set(frame.time_key.astype(str))
            if not keys-last_keys or (next_token is not None and str(next_token) in tokens):
                raise ValueError('HISTORY_PAGINATION_NO_PROGRESS')
            pages.append(frame);last_keys.update(keys)
            if next_token is None:break
            tokens.add(str(next_token));token=next_token;time.sleep(3.1)
        else:raise ValueError('HISTORY_PAGE_LIMIT_EXCEEDED')
    finally:ctx.close()
    raw=pd.concat(pages,ignore_index=True)
    stamps=pd.to_datetime(raw.time_key).dt.tz_localize(args.timezone,ambiguous='raise',nonexistent='raise').dt.tz_convert('UTC')
    raw['ts_start_utc']=stamps-(pd.Timedelta(minutes=1) if args.semantics=='end' else pd.Timedelta(0))
    raw['contract']=args.contract
    from .core import calendar
    cal=calendar(args.start,args.end)
    # Single actual contract only. Selection is fixed before all bars, no hidden rollover.
    roll=pd.DataFrame(dict(session_date=cal.index.strftime('%Y-%m-%d'),contract=args.contract,
        expires_on=args.expires_on,known_at_utc=(cal.iloc[0].open-pd.Timedelta(days=1)).isoformat()))
    return import_data(args.root,args.product,raw,roll,args.start,args.end,'FUTU_TIMEZONE_AND_SEMANTICS_USER_DECLARED')


def backtest(root,product):
    folder=root/'data'/product
    if not (folder/'manifest.json').exists():raise ValueError('FUTURES_DATASET_MISSING_IMPORT_OR_COLLECT_FIRST')
    if sha(folder/'manifest.json')!=(folder/'manifest.sha256').read_text():raise ValueError('REGISTERED_MANIFEST_CHANGED')
    manifest=json.loads((folder/'manifest.json').read_text())
    out=root/'artifacts'/product/'orb10_3r_futures_v1/train'
    if out.exists():raise ValueError('RESEARCH_RESULTS_ALREADY_EXIST')
    if not manifest['formal_split_eligible']:raise ValueError('MINIMUM_500_SESSIONS_REQUIRED')
    if manifest['source_sha256']!=sha(Path(__file__).with_name('core.py')):raise ValueError('REGISTERED_RULE_CHANGED')
    if sha(folder/'minute.csv')!=manifest['minute_sha256'] or sha(folder/'roll_map.csv')!=manifest['roll_sha256']:
        raise ValueError('REGISTERED_INPUT_CHANGED')
    costs_path=root/'state'/('costs_'+product+'.json')
    if not costs_path.exists():raise ValueError('ROUND_TRIP_FEES_AND_SLIPPAGE_REQUIRED')
    costs=json.loads(costs_path.read_text())
    reg=out/'registration.json'
    save(reg,dict(rule=RULE,costs=costs,input_manifest_sha256=sha(folder/'manifest.json'),
        registered_at_utc=pd.Timestamp.now(tz='UTC').isoformat(),split='train'))
    raw=pd.read_csv(folder/'minute.csv');roll=pd.read_csv(folder/'roll_map.csv')
    dates=manifest['splits']['train']
    train=raw[raw.session_date.isin(dates)]
    mapping=roll[roll.session_date.isin(dates)]
    train,cal=validate(train,mapping,product,dates[0],dates[-1])
    daily=run(train,cal,product,costs['round_trip_fee_usd'],costs['slippage_ticks'])
    trades=daily[daily.status=='COMPLETE'];quarter=daily.assign(quarter=pd.to_datetime(daily.session_date).dt.to_period('Q').astype(str)).groupby('quarter').net_usd.agg(['count','mean','sum'])
    save(out/'daily.csv',daily.to_csv(index=False));save(out/'trades.csv',trades.to_csv(index=False));save(out/'quarterly.csv',quarter.to_csv())
    summary=dict(product=product,sessions=len(daily),trades=len(trades),net_usd=float(daily.net_usd.sum()),
        mean_trade_usd=float(trades.net_usd.mean()) if len(trades) else None,
        win_rate=float((trades.net_usd>0).mean()) if len(trades) else None,
        daily_drawdown_usd=float(daily.drawdown_usd.min()),costs=costs,
        hold_reference=hold_reference(train,product,costs['round_trip_fee_usd'],costs['slippage_ticks']),
        formal_data_gate=False,decision='WEAK_DIAGNOSTIC_TRAIN_ONLY',orders_enabled=False)
    save(out/'summary.json',summary)
    save(out/'report.md','# ES/MES Train诊断\n\n```json\n'+json.dumps(summary,indent=2)+'\n```\n\n一合约美元PnL，不是保证金收益率。未完成matched controls、bootstrap、成本资格、独立样本，不晋级KEEP。持有基准含隔夜、按明确换月重开，风险与时间暴露不同。\n')
    save(out/'optimization_choices.csv','option,status\nKEEP_FROZEN,AWAITING_USER_CHOICE\nQUALIFY_DATA_AND_COSTS,AWAITING_USER_CHOICE\nREGISTER_NEW_HYPOTHESIS,AWAITING_USER_CHOICE\n')
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description='Opt-in ES/MES research, no orders')
    parser.add_argument('command',choices=['status','select','probe','import-data','collect','costs','backtest'])
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--choice',choices=['none','ES','MES','both'])
    parser.add_argument('--product',choices=['ES','MES'])
    parser.add_argument('--input',type=Path);parser.add_argument('--roll-map',type=Path)
    parser.add_argument('--start');parser.add_argument('--end');parser.add_argument('--contract')
    parser.add_argument('--expires-on');parser.add_argument('--timezone');parser.add_argument('--semantics',choices=['start','end'])
    parser.add_argument('--round-trip-fee-usd',type=float);parser.add_argument('--slippage-ticks',type=int)
    parser.add_argument('--cost-basis',choices=['ASSUMED','VERIFIED'])
    args=parser.parse_args(argv);args.root=args.root.resolve()
    try:
        if args.command=='status':
            probe_path=args.root/'artifacts/probe.json'
            permissions=json.loads(probe_path.read_text())['products'] if probe_path.exists() else {}
            result=dict(selected=selection(args.root),orders_enabled=False,
                datasets={p:(args.root/'data'/p/'manifest.json').exists() for p in SPECS},
                costs_configured={p:(args.root/'state'/('costs_'+p+'.json')).exists() for p in SPECS},
                permissions=permissions)
        elif args.command=='select':
            if args.choice is None:parser.error('--choice required')
            save(args.root/'state/selection.json',dict(choice=args.choice,orders_enabled=False));result=dict(selected=selection(args.root),orders_enabled=False)
        elif args.command=='probe':result=probe(args.root)
        else:
            if not args.product:parser.error('--product required')
            if args.command=='costs':
                import math
                if args.round_trip_fee_usd is None or not math.isfinite(args.round_trip_fee_usd) or args.round_trip_fee_usd<0 or args.slippage_ticks is None or args.slippage_ticks<0 or not args.cost_basis:
                    raise ValueError('EXPLICIT_COSTS_REQUIRED')
                file=args.root/'state'/('costs_'+args.product+'.json')
                if (args.root/'artifacts'/args.product/'orb10_3r_futures_v1/train').exists():raise ValueError('COSTS_LOCKED_AFTER_RESEARCH')
                save(file,dict(round_trip_fee_usd=args.round_trip_fee_usd,slippage_ticks=args.slippage_ticks,basis=args.cost_basis))
                result=dict(status='COST_ASSUMPTIONS_SAVED',product=args.product)
            else:
                allowed(args.root,args.product)
                if args.command=='backtest':result=backtest(args.root,args.product)
                else:
                    if not args.start or not args.end:parser.error('--start and --end required')
                    for date in [args.start,args.end]:
                        if pd.Timestamp(date).strftime('%Y-%m-%d')!=date:raise ValueError('ISO_DATES_REQUIRED')
                    if args.start>args.end or args.end>=pd.Timestamp.now(tz='America/New_York').strftime('%Y-%m-%d'):
                        raise ValueError('COMPLETED_PRIOR_DATES_ONLY')
                    if args.command=='import-data':
                        if not args.input or not args.roll_map:parser.error('--input and --roll-map required')
                        result=import_data(args.root,args.product,pd.read_csv(args.input),pd.read_csv(args.roll_map),args.start,args.end,'USER_IMPORTED_REAL_DATA_NOT_INDEPENDENTLY_VERIFIED')
                    else:
                        if not all([args.contract,args.expires_on,args.timezone,args.semantics]):parser.error('--contract --expires-on --timezone --semantics required')
                        result=collect(args)
        print(json.dumps(result));return 0
    except Exception as exc:
        message=str(exc);safe=message if message.isupper() and len(message)<100 else 'CHECK_FUTURES_INPUTS_AND_PERMISSIONS'
        failure=dict(status='FAILED',error=safe,error_type=type(exc).__name__,orders_enabled=False)
        save(args.root/'logs'/(pd.Timestamp.now(tz='UTC').strftime('%Y%m%dT%H%M%S%fZ')+'.json'),failure)
        print(json.dumps(failure));return 1


if __name__=='__main__':raise SystemExit(main())
