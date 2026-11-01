"""独立ICT实时资格边界；v0.4冻结关闭，证据契约通过不构成授权。"""
import pandas as pd


def check_future_evidence_contract(report, structure, now):
    """未来提供者必须给出独立实时确认、实际到达记录及绑定版本的RTH证据。

    这里只验证接口契约；不认证证据真伪，不赋予实时资格。
    """
    try:
        proof=report['ict_live_evidence']
        if (report.get('mode')!='LIVE_OBSERVATION' or report.get('timeframe')!='1H'
                or proof.get('structure_realtime_confirmed') is not True
                or proof.get('arrival_times_verified') is not True
                or proof.get('rth_acceptance')!='PASSED' or not proof.get('acceptance_evidence_id')):
            return False
        if any(proof.get(k)!=report.get(k) or not report.get(k)
               for k in ('symbol','timeframe','version','parameter_version')):
            return False
        now=pd.Timestamp(now)
        verified=pd.Timestamp(proof['verified_at']);until=pd.Timestamp(proof['valid_until'])
        if verified.tzinfo is None or until.tzinfo is None or not verified<=now<=until:
            return False
        events=structure['evidence'];arrivals=proof['received_at_by_event']
        if not events or set(arrivals)!={e['id'] for e in events}:
            return False
        for event in events:
            arrived=pd.Timestamp(arrivals[event['id']]);confirmed=pd.Timestamp(event['confirmed_at'])
            if (event.get('source')!='FUTU_OPEND' or arrived.tzinfo is None
                    or not pd.Timestamp(event['bar_end'])<=arrived<=confirmed<=verified):
                return False
        return True
    except (KeyError,TypeError,ValueError,AttributeError,OverflowError):
        return False


def ict_live_qualification(report, structure, now):
    # 无运行时开关、qualified参数、数据库设置或离线测试解锁路径。
    # 独立实时提供者和真实RTH证据尚未验收，v0.4任何输入均不授予资格。
    return dict(qualified=False,contract_passed=check_future_evidence_contract(report,structure,now),
        status='PENDING_LIVE_ACCEPTANCE',
        reason='ICT结构独立实时确认、实际到达时间及相关RTH验收未通过；v0.4实时执行审查冻结关闭')
