"""Preregistered staged research. OOS never opens without validation and a lock."""
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from .storage import normalized, read, write_csv, write_json, atomic, digest
from .features import build, fit_states, apply_states
from .setups import detect, VARIANTS
from .outcomes import forward
from .inference import match, balance, bootstrap, holm

BASELINE=dict(version='baseline_v1',primary_horizon=30,horizons=[5,15,30,60],cost_bps=2.,seed=20261003,
              bootstrap_reps=10000,max_candidates=2,family_size=12,caliper=.5,embargo_sessions=1,
              warmup_sessions=60,tp_sl_enabled=False)

def source_hash():
    folder=Path(__file__).parent
    payload=''.join(name+digest(folder/name) for name in ['data.py','features.py','setups.py','outcomes.py','inference.py','research.py'])
    return hashlib.sha256(payload.encode()).hexdigest()

def corporate_dates(root):
    frame=read(root/'data/raw/corporate_actions.csv')
    names=[x for x in ['ex_div_date','ex_date'] if x in frame]
    if not names: raise ValueError('CORPORATE_ACTION_SCHEMA_UNQUALIFIED')
    return set(pd.to_datetime(frame[names[0]],errors='raise').dt.strftime('%Y-%m-%d'))

def preregister(root,start,end):
    minute,five,data=normalized(root)
    all_dates=sorted(minute.session_date.unique())
    dates=[d for d in all_dates if start<=d<=end]
    earlier=[d for d in all_dates if d<start]
    if len(earlier)<60: raise ValueError('DAILY_WARMUP_INSUFFICIENT')
    if len(dates)<500: raise ValueError('RESEARCH_SESSIONS_INSUFFICIENT')
    first=int(len(dates)*.6); second=int(len(dates)*.8)
    splits=dict(train=dates[:first],validation=dates[first+1:second],locked_oos=dates[second+1:],
                embargo=[dates[first],dates[second]],start=start,end=end)
    if len(splits['locked_oos'])<100: raise ValueError('OOS_SESSIONS_INSUFFICIENT')
    folder=root/'locks/baseline_v1'
    config=dict(**BASELINE,data_manifest_sha256=digest(root/'data/normalized/manifest.json'),splits=splits,
                registered_before_outcomes=True,registered_at_utc=datetime.now(timezone.utc).isoformat())
    if (folder/'registry.json').exists():
        old=json.loads((folder/'registry.json').read_text())
        for key in ['data_manifest_sha256','splits']:
            if old[key]!=config[key]: raise ValueError('REGISTERED_INPUTS_IMMUTABLE')
        return old
    hypotheses=[]
    for setup in VARIANTS:
        for direction in [1,-1]:
            hypotheses.append(dict(setup=setup,direction=direction,primary_horizon=30,cost_bps=2,
                family='PRIMARY_12',minimum_train_events=200,minimum_validation_events=100,
                minimum_oos_events=100,states='BASELINE_NO_FILTER',status='REGISTERED',tp_sl='DISABLED'))
    write_csv(folder/'research_registry.csv',pd.DataFrame(hypotheses))
    write_json(folder/'registry.json',config)
    return config

def context(root):
    folder=root/'locks/baseline_v1'
    registry=json.loads((folder/'registry.json').read_text())
    if digest(root/'data/normalized/manifest.json')!=registry['data_manifest_sha256']:
        raise ValueError('REGISTERED_DATA_CHANGED')
    minute,five,data=normalized(root)
    frame=build(minute,five,corporate_dates(root))
    model_path=folder/'state_model.json'
    if model_path.exists(): model=json.loads(model_path.read_text())
    else:
        model=fit_states(frame,registry['splits']['train']); write_json(model_path,model)
    frame=apply_states(frame,model)
    frame['split']='WARMUP'
    for name in ['train','validation','locked_oos']:
        frame.loc[frame.session_date.isin(registry['splits'][name]),'split']=name
    bars,events=detect(frame)
    if not events.empty: events['split']=events.bar_id.map(bars.split)
    return minute,bars,events,data,registry,model

def controls_returns(minute,bars,horizon=30,delay=0):
    result={}
    groups={date:part for date,part in bars.groupby('session_date')}
    for date,chunk in minute.groupby('session_date'):
        part=groups.get(date)
        if part is None: continue
        chunk=chunk.sort_values('ts_start_utc')
        starts=chunk.ts_start_utc.astype('int64').to_numpy()
        positions=np.searchsorted(starts,part.ts_end_utc.astype('int64').to_numpy())+delay
        valid=positions+horizon<=len(chunk)
        opens=chunk.open.to_numpy(); closes=chunk.close.to_numpy()
        for i,pos in zip(part.index[valid],positions[valid]):
            result[int(i)]=float((closes[pos+horizon-1]/opens[pos]-1)*10000)
    return result

def robustness(minute,bars,events,outcomes,setup,direction,probes):
    primary=outcomes[(outcomes.horizon==30)&(outcomes.status=='VALID')]
    checks=[]
    gross=primary.gross_bps
    for cost in [0,2,4,8]: checks.append(dict(case=f'cost_{cost}bps',events=len(gross),net_mean=float((gross-cost).mean()) if len(gross) else None))
    for delay in [1,2]:
        table=forward(minute,events,horizons=[30],delay=delay)
        values=table.loc[table.status=='VALID','net_bps'] if not table.empty else pd.Series(dtype=float)
        checks.append(dict(case=f'delay_{delay}m',events=len(values),net_mean=float(values.mean()) if len(values) else None))
    if not primary.empty:
        top=primary.groupby('session_date').net_bps.sum().nlargest(5).index
        remaining=primary[~primary.session_date.isin(top)]
        checks.append(dict(case='remove_top5_dates',events=len(remaining),net_mean=float(remaining.net_bps.mean()) if len(remaining) else None))
        primary=primary.copy(); primary['quarter']=pd.to_datetime(primary.session_date).dt.to_period('Q').astype(str)
        for quarter,part in primary.groupby('quarter'):
            checks.append(dict(case='quarter_'+quarter,events=len(part),net_mean=float(part.net_bps.mean())))
        for state in ['gap_state','volatility_state']:
            lookup=events.set_index('event_id')[state]
            for label,part in primary.groupby(primary.event_id.map(lookup)):
                checks.append(dict(case=state+'_'+label,events=len(part),net_mean=float(part.net_bps.mean())))
    # Perturbations are stability probes; never substitute the best point.
    if setup.startswith('ORB'):
        for alternate in ['ORB5','ORB15','ORB30']:
            alt=bars[bars[f'trigger_{alternate}_{direction}']].groupby('session_date').head(1)
            alt_events=pd.DataFrame([dict(event_id=f'probe_{i}',bar_id=i,session_date=r.session_date,setup=alternate,direction=direction,signal_time=r.ts_end_utc) for i,r in alt.iterrows()])
            values=forward(minute,alt_events,[30]) if not alt_events.empty else pd.DataFrame()
            valid=values[values.status=='VALID'] if not values.empty else values
            checks.append(dict(case='neighbor_'+alternate,events=len(valid),net_mean=float(valid.net_bps.mean()) if not valid.empty else None))
    else:
        for factor in [.8,1.,1.2]:
            all_events=probes[factor]
            alt=all_events[(all_events.setup==setup)&(all_events.direction==direction)]
            values=forward(minute,alt,[30])
            valid=values[values.status=='VALID'] if not values.empty else values
            checks.append(dict(case=f'neighbor_{factor}',events=len(valid),net_mean=float(valid.net_bps.mean()) if not valid.empty else None))
    quarter=[c for c in checks if c['case'].startswith('quarter_') and c['events']>=20]
    neighbor=[c for c in checks if c['case'].startswith('neighbor_') and c['events']>=20]
    critical=[c for c in checks if c['case'] in ['cost_4bps','delay_1m','remove_top5_dates']]
    passed=bool(len(quarter)>=3 and sum(c['net_mean']>0 for c in quarter)/len(quarter)>=2/3
        and len(neighbor)>=3 and sum(c['net_mean']>0 for c in neighbor)/len(neighbor)>=2/3
        and len(critical)==3 and all(c['net_mean'] is not None and c['net_mean']>0 for c in critical))
    return checks,passed

def evaluate(root,split,candidates=None):
    if split not in ['train','validation','locked_oos']: raise ValueError('UNKNOWN_SPLIT')
    minute,bars,events,data,registry,model=context(root)
    folder=root/'artifacts/research/baseline_v1'/split
    lock_folder=root/'locks/baseline_v1'
    if split=='locked_oos':
        lock=json.loads((lock_folder/'lock_manifest.json').read_text())
        if lock['source_sha256']!=source_hash(): raise ValueError('LOCKED_SOURCE_CHANGED')
        if lock['data_sha256']!=registry['data_manifest_sha256']: raise ValueError('LOCKED_DATA_CHANGED')
        candidates=lock['candidates']
    if split!='train' and not candidates: raise ValueError('NO_VALIDATED_CANDIDATES')
    if split!='train' and folder.exists(): raise ValueError('HOLDOUT_ALREADY_CONSUMED')
    folder.parent.mkdir(parents=True,exist_ok=True)
    folder.mkdir(exist_ok=split=='train')
    access=dict(split=split,started_at_utc=datetime.now(timezone.utc).isoformat(),source_sha256=source_hash(),
                data_sha256=registry['data_manifest_sha256'],status='RUNNING')
    write_json(folder/'access_audit.json',access)
    # Split mask before outcome computation: never use holdout returns for Train selection.
    dates=registry['splits'][split]; subset=bars[bars.split==split]
    subset_events=events[events.session_date.isin(dates)]
    subset_minute=minute[minute.session_date.isin(dates)]
    pairs=candidates or [dict(setup=s,direction=d) for s in VARIANTS for d in [1,-1]]
    control_gross=controls_returns(subset_minute,subset)
    probes={1.:subset_events}
    for factor in [.8,1.2]: probes[factor]=detect(subset,scale=factor)[1]
    subset=subset[subset.index.isin(control_gross)]
    summaries=[]; all_outputs=[]; all_links=[]; all_checks=[]
    for pair in pairs:
        setup=pair['setup']; direction=pair['direction']
        chosen=subset_events[(subset_events.setup==setup)&(subset_events.direction==direction)]
        outcome=forward(subset_minute,chosen)
        if outcome.empty:
            summaries.append(dict(setup=setup,direction=direction,events=0,days=0,p_raw=1.,decision='WEAK',reason='INSUFFICIENT_EVENTS',sample_pass=False)); continue
        primary=outcome[(outcome.horizon==30)&(outcome.status=='VALID')]
        chosen=chosen[chosen.event_id.isin(primary.event_id)]
        links=match(subset,chosen,model['matching_scale'],split)
        bal=balance(bars,chosen,links,model['matching_scale'])
        ctr={i:direction*g-2 for i,g in control_gross.items()}
        stats=bootstrap(primary,links,ctr,dates)
        moving=bootstrap(primary,links,ctr,dates,block=5)
        checks,robust=robustness(subset_minute,subset,chosen,outcome,setup,direction,probes)
        for check in checks: all_checks.append(dict(setup=setup,direction=direction,split=split,**check))
        count_gate=len(primary)>=(200 if split=='train' else 100) and primary.session_date.nunique()>=(100 if split=='train' else 60)
        summary=dict(setup=setup,direction=direction,events=len(primary),days=int(primary.session_date.nunique()),
            net_mean=stats['net_mean'],delta_mean=stats['delta_mean'],net_ci_low=stats['net_ci'][0],net_ci_high=stats['net_ci'][1],
            delta_ci_low=stats['delta_ci'][0],delta_ci_high=stats['delta_ci'][1],
            moving_net_ci_low=moving['net_ci'][0],moving_delta_ci_low=moving['delta_ci'][0],
            match_fraction=bal['match_fraction'],smd_max=bal['smd_max'],control_gate=bal['pass_gate'],
            sample_pass=bool(count_gate),robustness_pass=robust,p_raw=max(stats['p_net'],stats['p_delta']),
            win_rate=float((primary.net_bps>0).mean()),median_bps=float(primary.net_bps.median()),
            breakeven_cost_bps=float(primary.gross_bps.mean()),decision='WEAK',reason='PENDING_GATES')
        summaries.append(summary); all_outputs.append(outcome); all_links.append(links)
        print(json.dumps(dict(stage='RESEARCH',split=split,setup=setup,direction=direction,events=len(primary))),flush=True)
    adjusted=holm([s['p_raw'] for s in summaries])
    for summary,p in zip(summaries,adjusted):
        summary['p_adjusted']=p; summary['formal_data_gate']=data['formal_data_gate']
        if not summary.get('sample_pass'):
            summary.update(decision='WEAK',reason='INSUFFICIENT_EVENTS_OR_DAYS'); continue
        if not data['formal_data_gate']:
            summary.update(decision='WEAK',reason='DATA_QUALIFICATION_PENDING'); continue
        if not summary.get('control_gate'):
            summary.update(decision='WEAK',reason='MATCHING_GATE_FAILED'); continue
        if summary['net_mean']<=0 or summary['delta_mean'] is None or summary['delta_mean']<=0:
            summary.update(decision='NO EDGE',reason='NONPOSITIVE_NET_OR_INCREMENTAL_EDGE'); continue
        significant=summary['net_ci_low'] is not None and summary['delta_ci_low'] is not None and summary['net_ci_low']>0 and summary['delta_ci_low']>0 and p<.05
        significant &= summary['moving_net_ci_low'] is not None and summary['moving_net_ci_low']>0 and summary['moving_delta_ci_low'] is not None and summary['moving_delta_ci_low']>0
        if significant and summary['net_mean']>=2 and summary['delta_mean']>=1 and summary['robustness_pass']:
            summary.update(decision='KEEP',reason='PREDECLARED_GATES_PASSED')
        else: summary.update(decision='WEAK',reason='INFERENCE_OR_ROBUSTNESS_GATE_FAILED')
    summary_frame=pd.DataFrame(summaries)
    write_csv(folder/'edge_summary.csv',summary_frame)
    write_csv(folder/'events.csv',subset_events)
    write_csv(folder/'market_states.csv',subset)
    write_csv(folder/'forward_returns.csv',pd.concat(all_outputs,ignore_index=True) if all_outputs else pd.DataFrame())
    write_csv(folder/'matched_controls.csv',pd.concat(all_links,ignore_index=True) if all_links else pd.DataFrame())
    write_csv(folder/'robustness.csv',pd.DataFrame(all_checks))
    keep=[dict(setup=s['setup'],direction=s['direction']) for s in summaries if s['decision']=='KEEP'][:2]
    report='# '+split+' research\n\nDiagnostic evidence; event-study returns are not portfolio returns.\n\n'+summary_frame.to_csv(index=False)+'\n\nFormal data gate: '+str(data['formal_data_gate'])+'\n\nCandidates eligible for next stage: '+json.dumps(keep)+'\n'
    atomic(folder/'decision.md',report)
    write_json(folder/'result.json',dict(split=split,candidates=keep,formal_data_gate=data['formal_data_gate'],source_sha256=source_hash(),
                                       input_sha256=registry['data_manifest_sha256']))
    access['status']='SUCCESS'; write_json(folder/'access_audit.json',access)
    return keep

def lock(root):
    path=root/'locks/baseline_v1/lock_manifest.json'
    if path.exists(): raise ValueError('LOCK_ALREADY_EXISTS')
    result=json.loads((root/'artifacts/research/baseline_v1/validation/result.json').read_text())
    if not result['candidates'] or not result['formal_data_gate']: raise ValueError('NO_VALIDATED_CANDIDATES')
    if result['source_sha256']!=source_hash(): raise ValueError('VALIDATION_SOURCE_CHANGED')
    if result['input_sha256']!=digest(root/'data/normalized/manifest.json'): raise ValueError('VALIDATION_DATA_CHANGED')
    write_json(path,dict(version='baseline_v1',source_sha256=source_hash(),data_sha256=result['input_sha256'],
                        candidates=result['candidates'],created_at_utc=datetime.now(timezone.utc).isoformat(),cost_bps=2,
                        horizon=30,tp_sl_enabled=False))
    return path
