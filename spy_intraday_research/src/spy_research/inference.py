"""Matched controls and date-cluster inference with reused controls preserved."""
import numpy as np
import pandas as pd

def match(bars,events,scale,split,seed=20261003):
    """Match only pre-trigger gap and lagged volatility; never outcomes."""
    rng=np.random.default_rng(seed); links=[]; diagnostics=[]
    for event in events.itertuples():
        row=bars.loc[event.bar_id]
        pool=bars[(bars.split==split)&(bars.session_date!=event.session_date)&(bars.bucket==row.bucket)
                  &(bars.gap_state==row.gap_state)&(bars.volatility_state==row.volatility_state)
                  &~bars[f'trigger_{event.setup}_{event.direction}']]
        distance=np.zeros(len(pool)); within=np.ones(len(pool),dtype=bool)
        for col in ['gap_ratio','volatility']:
            std=scale[col]
            if not np.isfinite(std) or std<=0: within[:]=False; continue
            diff=(pool[col].to_numpy()-row[col])/std
            within&=np.isfinite(diff)&(np.abs(diff)<=.5)
            distance+=diff**2
        candidates=pool.loc[within].copy()
        candidates['distance']=np.sqrt(distance[within])
        candidates['tie']=rng.random(len(candidates))
        chosen=candidates.sort_values(['distance','tie']).head(5)
        for control_id,control in chosen.iterrows():
            links.append(dict(event_id=event.event_id,event_bar_id=event.bar_id,event_date=event.session_date,
                control_id=int(control_id),control_date=control.session_date,setup=event.setup,
                direction=event.direction,weight=1/len(chosen),distance=float(control.distance)))
    return pd.DataFrame(links,columns=['event_id','event_bar_id','event_date','control_id','control_date','setup','direction','weight','distance'])

def balance(bars,events,links,scale):
    if events.empty or links.empty: return dict(match_fraction=0.,smd_max=None,pass_gate=False)
    matched=events[events.event_id.isin(links.event_id)]
    grouped=links.groupby('event_id')
    diffs=[]
    for col in ['gap_ratio','volatility']:
        treated=bars.loc[matched.bar_id,col].mean()
        control=links.control_id.map(bars[col])*links.weight
        mean=control.groupby(links.event_id).sum().mean()
        diffs.append(abs(float((treated-mean)/scale[col])))
    fraction=len(matched)/len(events)
    return dict(match_fraction=float(fraction),smd_max=max(diffs),pass_gate=bool(fraction>=.8 and max(diffs)<=.1))

def bootstrap(treated,links,control_returns,dates,reps=10000,seed=20261003,block=1):
    """Date weights apply jointly to events AND reused control-date observations.

    The fixed matched estimator is reweighted within each event's control set.
    Controls with zero bootstrap weight cannot remain in that replicate.
    """
    if treated.empty: return dict(net_mean=None,delta_mean=None,net_ci=[None,None],delta_ci=[None,None],p_net=1.,p_delta=1.,valid_reps=0)
    rng=np.random.default_rng(seed); dates=list(dates); index={d:i for i,d in enumerate(dates)}
    event_index={eid:i for i,eid in enumerate(treated.event_id)}
    ev_dates=np.array([index[d] for d in treated.session_date]); net=treated.net_bps.to_numpy()
    links=links[links.event_id.isin(event_index)&links.control_id.isin(control_returns)].copy()
    control_dates=np.zeros((len(treated),5),dtype=int)
    control_weights=np.zeros((len(treated),5))
    control_values=np.zeros((len(treated),5))
    slots=np.zeros(len(treated),dtype=int)
    for row in links.itertuples():
        i=event_index[row.event_id]; j=index[row.control_date]
        slot=slots[i]
        if slot>=5: raise ValueError('CONTROL_COUNT_EXCEEDED')
        control_dates[i,slot]=j; control_weights[i,slot]=row.weight
        control_values[i,slot]=control_returns[row.control_id]; slots[i]+=1
    base_den=control_weights.sum(axis=1); base_num=(control_weights*control_values).sum(axis=1)
    has=base_den>0
    delta=float(np.mean(net[has]-base_num[has]/base_den[has])) if has.any() else None
    samples_net=[]; samples_delta=[]
    for offset in range(0,reps,256):
        count=min(256,reps-offset)
        if block==1: draws=rng.integers(0,len(dates),size=(count,len(dates)))
        else:
            starts=rng.integers(0,len(dates),size=(count,int(np.ceil(len(dates)/block))))
            draws=((starts[:,:,None]+np.arange(block))%len(dates)).reshape(count,-1)[:,:len(dates)]
        weights=np.zeros((count,len(dates)))
        np.add.at(weights,(np.repeat(np.arange(count),len(dates)),draws.ravel()),1)
        event_weight=weights[:,ev_dates]
        reweighted=weights[:,control_dates]*control_weights[None,:,:]
        den=reweighted.sum(axis=2); num=(reweighted*control_values[None,:,:]).sum(axis=2)
        valid=den>0
        values=net[None,:]-np.divide(num,den,out=np.zeros_like(num),where=valid)
        delta_weight=event_weight*valid
        net_total=event_weight.sum(axis=1); delta_total=delta_weight.sum(axis=1)
        samples_net.extend(np.divide(event_weight@net,net_total,out=np.full(count,np.nan),where=net_total>0))
        samples_delta.extend(np.divide((delta_weight*values).sum(axis=1),delta_total,out=np.full(count,np.nan),where=delta_total>0))
    def describe(samples,point):
        clean=np.asarray(samples); clean=clean[np.isfinite(clean)]
        if point is None or len(clean)<reps*.95: return [None,None],1.,len(clean)
        ci=np.quantile(clean,[.025,.975]).tolist()
        # Null-centered two-sided cluster bootstrap, finite-sample +1 correction.
        p=float((1+np.sum(np.abs(clean-point)>=abs(point)))/(len(clean)+1))
        return ci,p,len(clean)
    net_mean=float(net.mean()); nci,pn,ncount=describe(samples_net,net_mean)
    dci,pd_,dcount=describe(samples_delta,delta)
    return dict(net_mean=net_mean,delta_mean=delta,net_ci=nci,delta_ci=dci,p_net=pn,p_delta=pd_,valid_reps=min(ncount,dcount))

def holm(pvalues,family_size=12):
    """Preserve preregistered family, including absent hypotheses as p=1."""
    values=np.asarray(pvalues,dtype=float)
    if len(values)>family_size: raise ValueError('STATISTICAL_FAMILY_EXCEEDED')
    padded=np.r_[values,np.ones(family_size-len(values))]
    order=np.argsort(padded,kind='stable'); result=np.ones(family_size); running=0.
    for rank,i in enumerate(order):
        running=max(running,min(1.,float(padded[i]*(family_size-rank))))
        result[i]=running
    return result[:len(values)].tolist()
