import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]/'strategies/v23c'


def test_original_bytes_and_order_calls_are_preserved_in_alert_copy():
    original=(ROOT/'original.pine').read_bytes()
    copy=(ROOT/'QQQAV23C_P0_Alerts_V1.pine').read_bytes()
    assert hashlib.sha256(original).hexdigest()=='bb098c7fa0b5f88299df2f154a30edb2e80a6e0b25e0331cb61c7c9b4e8778e6'
    assert copy==original+(ROOT/'alerts_append.pine').read_bytes()
    # The new appendix must never introduce an order or change a model variable.
    appendix=(ROOT/'alerts_append.pine').read_text(encoding='utf-8')
    assert not re.search(r'strategy\.(?:order|entry|close|exit|cancel)',appendix)
    assert not re.search(r'(?m)^\s*(?:targetExposurePct|shouldRebalance|baseMode|boostMode|usePartialCloseForReduce)\s*:?=',appendix)


def test_native_fill_template_maps_first_seven_original_plot_outputs():
    original=(ROOT/'original.pine').read_text(encoding='utf-8')
    plots=re.findall(r'(?m)^plot\(([^,]+),\s*"([^"]+)"',original)
    assert plots[6][0]=='usePartialCloseForReduce ? 1 : 0'
    template=(ROOT/'fill_message.txt').read_text(encoding='utf-8')
    assert '{{plot_6}}' in template
    substitutions={'plot_6':'1','exchange':'NASDAQ','ticker':'QQQ','interval':'D',
        'time':'2026-11-16T14:30:00Z','timenow':'2026-11-16T14:30:01Z',
        'strategy.order.id':'Rebalance Long','strategy.order.comment':'Increase',
        'strategy.order.action':'buy','strategy.order.contracts':'2',
        'strategy.order.price':'100','strategy.position_size':'20'}
    for name,value in substitutions.items(): template=template.replace('{{'+name+'}}',value)
    payload=json.loads(template)
    from desk.v23c_signals import validate
    from datetime import datetime,timezone
    event=validate(payload,datetime(2026,11,16,14,30,2,tzinfo=timezone.utc))
    assert event['event']=='MODEL_FILL' and event['action']=='INCREASE'
