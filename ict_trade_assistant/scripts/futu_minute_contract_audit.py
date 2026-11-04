"""独立分钟契约审计v1；只读保存样本，不生成映射后行情或ICT事件。"""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import importlib.metadata
import json
import math

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'data/post_close_supplement/20261102_20261103_01'
VERSION='FUTU_MINUTE_CONTRACT_AUDIT_V1'
FIELDS=('open','high','low','close','volume')


def qualification():
    # 只有原始分钟标签、OHLC或数量无法证明真实区间。此版本不授予资格。
    return dict(version=VERSION,status='TIME_CONTRACT_UNRESOLVED',qualified=False,
                signal_status='UNKNOWN',ict_realtime=False,quarantine_minutes=2)


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def values(row):return {k:row[k] for k in ('time_key',*FIELDS)} if row else None


def compare(left,right):
    return {k:dict(left=left[k],right=right[k],delta=float(left[k])-float(right[k]),
                   equal=math.isclose(float(left[k]),float(right[k]),abs_tol=1e-8,rel_tol=0)) for k in FIELDS}


def aggregate(rows):
    if not rows:return None
    return dict(open=rows[0]['open'],high=max(r['high'] for r in rows),low=min(r['low'] for r in rows),
                close=rows[-1]['close'],volume=sum(r['volume'] for r in rows))


def audit(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    report=dict(**qualification(),source_directory=str(SOURCE),files={},cases=[],
        sdk_installed_now=importlib.metadata.version('futu-api'),
        sdk_at_acquisition='未直接记录；冻结requirements-lock.txt为futu_api==10.12.7208，不能替代采集当时版本记录',
        opend_at_acquisition=load(SOURCE/'probe.json')['state']['server_ver'],
        request_parameters=dict(start='2026-10-30',end='2026-11-02',ktype='K_1M / K_DAY',autype='NONE',
            session=['RTH','ALL'],extended_time='未传入，SDK默认False；显式session覆盖extended_time',max_count=1000,
            provenance='从保存的collect.py及collect_all.py重建参数；原始页保留请求/响应时间和分页状态'),
        interval_truth='UNRESOLVED：缺少分钟区间的权威字段说明、逐笔区间重构或同期到达证据')
    for p in SOURCE.iterdir():
        if p.is_file() and ('raw' in p.name or '-page' in p.name or p.name in ('collect.py','collect_all.py','probe.json')):
            report['files'][p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
    for symbol in ('SPY','QQQ','IWM','SOXX'):
        raw=load(SOURCE/(symbol+'-raw.json'));all_raw=load(SOURCE/('ALL-'+symbol+'-raw.json'))
        for day in ('2026-10-30','2026-11-02'):
            rows=sorted([r for r in raw['periods']['minute']['rows'] if r['time_key'].startswith(day)],key=lambda r:r['time_key'])
            all_rows=sorted([r for r in all_raw['rows'] if r['time_key'].startswith(day)],key=lambda r:r['time_key'])
            by_all={r['time_key']:r for r in all_rows};by_rth={r['time_key']:r for r in rows}
            daily=next(r for r in raw['periods']['daily']['rows'] if r['time_key'].startswith(day))
            clock=[r for r in all_rows if day+' 09:30:00'<=r['time_key']<day+' 16:00:00']
            inclusive=[r for r in all_rows if day+' 09:30:00'<=r['time_key']<=day+' 16:00:00']
            without_close=[r for r in rows if r['time_key']<day+' 16:00:00']
            common=[r for r in rows if r['time_key'] in by_all]
            equal=sum(all(v['equal'] for v in compare(r,by_all[r['time_key']]).values()) for r in common)
            sets=dict(vendor_RTH=rows,ALL_clock_start_grid=clock,ALL_inclusive_boundaries=inclusive,
                      RTH_without_1600=without_close,ALL_calendar_date=all_rows)
            totals={k:dict(rows=len(v),ohlcv=aggregate(v),daily_differences=compare(aggregate(v),daily)) for k,v in sets.items()}
            mapped=[datetime.fromisoformat(day+'T'+t).replace(tzinfo=ZoneInfo('America/New_York')) for t in ('09:30:00','09:31:00','15:59:00','16:00:00')]
            candidates=[
                dict(name='A：RTH标签直接视为分钟开始',status='不能授予资格',evidence='缺少09:30并出现16:00；与冻结开始网格不一致，16:00是否属于盘后尚无区间定义证明'),
                dict(name='B：RTH标签视为分钟结束',status='UNRESOLVED',evidence='首尾与日线OHLC相符、端点可解释；没有逐分钟真实区间证据，不能因此选定或平移全体时间戳'),
                dict(name='C：按ALL的09:30至15:59作为RTH',status='不能授予资格',evidence='形成390个标签但包含供应商RTH集以外09:30、排除其16:00；原生日线首尾价格差异见原始比较'),
                dict(name='D：删除RTH的16:00',status='不成立于冻结完整网格',evidence='仅389条，仍缺09:30；不可删除收盘记录来通过检查'),
                dict(name='E：保留16:00并插入ALL的09:30',status='不能授予资格',evidence='391条，混入会话外候选；没有新增真实开盘分钟证据，禁止补造')]
            case=dict(symbol=symbol,day=day,first_five=[dict(RTH=values(r),ALL=values(by_all.get(r['time_key']))) for r in rows[:5]],
                last_five=[dict(RTH=values(r),ALL=values(by_all.get(r['time_key']))) for r in rows[-5:]],
                all_0930_vs_rth_0931=compare(by_all[day+' 09:30:00'],by_rth[day+' 09:31:00']),
                rth_1559_vs_1600=compare(by_rth[day+' 15:59:00'],by_rth[day+' 16:00:00']),
                boundary_rows={t:dict(RTH=values(by_rth.get(day+' '+t)),ALL=values(by_all.get(day+' '+t))) for t in ('09:30:00','09:31:00','15:59:00','16:00:00')},
                daily=values(daily),native_open_vs_candidates={t:float(by_all[day+' '+t]['open'])-float(daily['open']) for t in ('09:30:00','09:31:00')},
                native_close_vs_candidates={t:float(by_all[day+' '+t]['close'])-float(daily['close']) for t in ('15:59:00','16:00:00')},
                minute_sets=totals,shared_labels=len(common),shared_ohlcv_equal=equal,candidates=candidates,
                timezone=[dict(new_york=x.isoformat(),hong_kong=x.astimezone(ZoneInfo('Asia/Hong_Kong')).isoformat()) for x in mapped],
                conclusion='TIME_CONTRACT_UNRESOLVED',source_rows_modified=False)
            report['cases'].append(case)
    (output/'minute-contract-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Futu分钟时间契约独立审计','',f'版本：{VERSION}。结论：**TIME_CONTRACT_UNRESOLVED**。正式ICT结构资格关闭，信号UNKNOWN。','',
        '审计仅使用保存的原始RTH、ALL、原生日线；逐证券逐日输出首尾各5根、四个边界标签、全部OHLCV差值、5类分钟集合的累计量及日线差值。详见data/rth_recovery_v2/deployment_20261103/contract/minute-contract-audit.json。',
        '', '| 证券 | 交易日 | 共同标签/全字段相同 | RTH首尾 | 供应商RTH累计量 | 原生日线量 | 差值 |','|---|---|---:|---|---:|---:|---:|']
    for c in report['cases']:
        total=c['minute_sets']['vendor_RTH'];v=total['daily_differences']['volume']
        lines.append(f"| {c['symbol']} | {c['day']} | {c['shared_labels']}/{c['shared_ohlcv_equal']} | 09:31–16:00 | {v['left']:g} | {v['right']:g} | {v['delta']:g} |")
    lines += ['', '候选方案逐案均有独立记录。A与冻结网格矛盾；B作为结束标签假说与首尾价格相容但未获区间定义证明；C的390根包含供应商RTH集以外的09:30并排除16:00；D只剩389根；E形成391根且混入不同集合。没有选择一个方案用于正式计算，也没有生成减一分钟后的行情。',
        '', '不能仅凭390根或32项OHLC聚合相等通过。共同标签一致只证明两种请求返回相同记录，不能证明标签对应的真实成交区间。缺少开盘分钟、附加盘后分钟、结束标签的三种解释目前不能唯一裁定。成交量差异保留UNRESOLVED，没有用补值或删值配平。',
        '', '10月30日使用EDT（UTC−4），09:30为香港21:30、16:00为次日04:00；11月2日使用EST（UTC−5），09:30为香港22:30、16:00为次日05:00。所有四个边界均逐案保存ISO时区。',
        '', 'OpenD采集时server_ver=1011；SDK采集当时未单独保存版本，冻结锁文件为10.12.7208，当前安装版本另记JSON。请求K_1M/K_DAY，AuType.NONE，Session.RTH或ALL，extended_time省略为默认False；显式Session覆盖extended_time。参数来源为保存的采集器代码及哈希，不能伪称原始响应包含全部参数。',
        '', '供应商正式区间说明、可核验逐笔重构或独立同期边界证据取得前，qualification()硬返回qualified=False；新版自动化不调用ICT识别器，也不向生产库导入这些分钟。',
        '', '参考：[Futu历史K线接口](https://openapi.futunn.com/futu-api-doc/quote/request-history-kline.html)：字段说明明确美股time_key使用美东时间，所查字段未明确每根分钟的开始/结束区间。']
    (ROOT/'FUTU_MINUTE_TIME_CONTRACT_AUDIT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    r=audit(ROOT/'data/rth_recovery_v2/deployment_20261103/contract')
    print(json.dumps(dict(status=r['status'],cases=len(r['cases']),qualified=r['qualified'])))
