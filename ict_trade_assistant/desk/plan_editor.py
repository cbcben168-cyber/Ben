"""独立编辑片段；不在行情定时片段中，未提交表单不会被定时重绘。"""
import streamlit as st
from .i18n import zh, details


@st.fragment
def editors(store,codes):
    with st.expander('备注与人工计划编辑（行情自动刷新时保留输入）'):
        selected=st.selectbox('编辑标的（独立于候选切换；切换前请保存草稿）',codes,
                              index=codes.index(st.session_state.desk_symbol),key='plan_edit_symbol')
        st.caption('这是人工辅助计划，不是已确认信号或成交记录。取消只停用该计划，不删除独立关注区域，不涉及任何订单。')
        with st.form('saved_note_'+selected):
            note=st.text_area('人工备注',value=store.note(selected),key='saved_note_text_'+selected)
            if st.form_submit_button('保存备注'):
                store.note(selected,note); st.success('备注已保存；刷新工作台可查看最新摘要。')
        plans=store.plans(selected)
        choice=st.selectbox('编辑计划',['新建']+[p['plan_id'] for p in plans],format_func=lambda v:'建立新计划' if v=='新建' else v)
        p=next((p for p in plans if p['plan_id']==choice),{})
        key=selected+choice+str(p.get('version',0))
        with st.form('plan_form_'+key):
            st.write('计划标的：'+selected)
            strategy=st.text_input('策略版本（人工计划标识，不更改冻结规则）',value=p.get('strategy_version','ICT-人工计划-v1'))
            direction=st.selectbox('计划方向',['LONG','SHORT'],index=1 if p.get('direction')=='SHORT' else 0,format_func=zh)
            low=st.number_input('入场区下限（美元）',min_value=0.,value=float(p.get('low',0)))
            high=st.number_input('入场区上限（美元）',min_value=0.,value=float(p.get('high',0)))
            invalid=st.number_input('失效价（美元）',min_value=0.,value=float(p.get('invalid',0)))
            tl=st.number_input('目标区下限（美元）',min_value=0.,value=float(p.get('target_low',0)))
            th=st.number_input('目标区上限（美元）',min_value=0.,value=float(p.get('target_high',0)))
            memo=st.text_area('计划备注',value=p.get('memo',''))
            evidence_note=st.text_area('结构证据补充（人工记录，不自动确认入场）',value=p.get('evidence_note',''))
            attach=st.checkbox('保存时附加当前决策证据快照',value=False)
            save=st.form_submit_button('保存计划',disabled=p.get('status')=='CANCELLED')
            cancel=st.form_submit_button('取消该计划',disabled=not p or p.get('status')=='CANCELLED')
            if save or cancel:
                payload=dict(symbol=selected,strategy_version=strategy,direction=direction,low=low,high=high,invalid=invalid,target_low=tl,target_high=th,memo=memo)
                payload.update(evidence_note=evidence_note,decision_evidence=p.get('decision_evidence'))
                if attach:
                    payload['decision_evidence']=st.session_state.get('v04_decisions',{}).get(selected)
                try:
                    store.save_plan(p if cancel else payload,p.get('plan_id'),p.get('version',0),cancel=cancel)
                    st.success('已保存历史版本。点击“载入最新计划”后查看或继续修改；刷新工作台可查看摘要。')
                except ValueError as exc: st.error(str(exc))
        if st.button('载入最新计划'): st.rerun(scope='fragment')
        if p:
            st.caption('建立时间：'+p['created_at']+' · 最近修改：'+p['updated_at'])
            with st.expander('计划历史版本'): st.json(details(store.plan_history(p['plan_id'])))
