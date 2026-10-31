"""历史事件展示；与实时触价提醒、人工计划价格相互独立。"""
LABELS = dict(WATCH='观察',SWEEP='扫荡与收回',MSS='结构收盘突破',FVG='公允价值缺口',
              CE='缺口中点触及',CE_REVIEW='中点人工复核',INVALIDATED='失效')
STATUS = dict(CONFIRMED='已确认',FORMING='形成中',NEW='新形成',WAITING_RETEST='等待回踩',
              TOUCHED='已触及',INVALIDATED='已失效',UNKNOWN='未知／不可用')


def review_text(report):
    if report['status']!='AVAILABLE':
        return '历史观察不可用：'+report['reason']+'。下一步检查分钟完整性与数据来源。'
    events=[e for e in report['events'] if e['kind']!='WATCH' and e['status']=='CONFIRMED']
    if not events:
        return '历史观察：未出现满足定义的已确认结构链。下一步核对流动性水平和已完成K线；不提供实时入场建议。'
    latest=events[-1]
    action=dict(SWEEP='核对固定Swing Pivot并等待收盘突破',MSS='核对方向FVG及第三根确认时间',
                FVG='等待形成柱之后的回踩并核对CE',CE='人工复核失效条件、数据时效及独立交易计划',
                INVALIDATED='关闭该观察链，检查失效原因，等待新条件')[latest['kind']]
    return f"历史观察：{LABELS[latest['kind']]}，确认 {latest['confirmed_at']}。下一步：{action}；不提供实时入场建议。"


def event_rows(report):
    return [dict(事件=LABELS.get(e['kind'],e['kind']),状态=STATUS.get(e['status'],e['status']),
                 方向={'LONG':'多向观察','SHORT':'空向观察','UNKNOWN':'方向未知'}[e['direction']],
                 关键价=e.get('level',e.get('structure_price',e.get('ce'))),
                 发生时间=e['occurred_at'],确认时间=e['confirmed_at'] or '尚未确认',
                 原因=e['reason'],策略版本=e['version'],参数版本=e['parameter_version'])
            for e in report['events'] if e['kind']!='WATCH']


def add_event_layers(fig, report):
    if report['status']!='AVAILABLE':return
    for kind in ['SWEEP','MSS','FVG','CE']:
        events=[e for e in report['events'] if e['kind']==kind and e['status']=='CONFIRMED'][-12:]
        if events:
            fig.add_scatter(x=[e['confirmed_at'] for e in events],
                            y=[e.get('level',e.get('structure_price',e.get('ce'))) for e in events],
                            text=[f"历史{LABELS[kind]} · 确认 {e['confirmed_at']} · {e['reason']}" for e in events],
                            mode='markers',marker=dict(size=9,symbol='diamond'),name='历史'+LABELS[kind],
                            hovertemplate='%{text}<br>价格 %{y:.4f}<extra></extra>')
    for zone in report['fvgs'][-12:]:
        when=zone['confirmed_at']
        fig.add_scatter(x=[when,when,when],y=[zone['low'],zone['ce'],zone['high']],mode='markers',
                        marker=dict(symbol='line-ew',size=12,color='gray' if zone['status']=='INVALIDATED' else 'cyan'),
                        name='历史缺口边界／中点',text=[f"历史FVG {STATUS[zone['status']]} · 确认 {when}"]*3,
                        hovertemplate='%{text}<br>价格 %{y:.4f}<extra></extra>')
