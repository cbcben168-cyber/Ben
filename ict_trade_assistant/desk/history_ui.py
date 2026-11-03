"""Daily coverage and offline import. Does not retrieve online market data."""
import json
import pandas as pd
import streamlit as st
from .history_import import DailyArchive, BLOCK


def coverage_rows(archive, entries, legacy):
    saved={r['symbol']:r for r in archive.coverage()}
    rows=[]
    for e in entries:
        c=e['symbol'];meta=saved.get(c)
        if legacy.get(c,{}).get('daily'):
            bars=legacy[c]['daily']
            rows.append(dict(证券=c,启用=e['enabled'],状态='原四ETF历史',日K=len(bars),起始=bars[0]['ts'][:10],截至=bars[-1]['ts'][:10],来源='FUTU原快照',取得时间=legacy[c]['health'].get('received_at','未知'),缺失交易日='沿用冻结证据',日线观察='原流程',ICT='原资格不变'))
        elif meta:
            rows.append(dict(证券=c,启用=e['enabled'],状态=meta['status'],日K=meta['bars'],起始=meta['first'],截至=meta['last'],来源=meta['source']+'/'+meta['feed'],取得时间=meta['acquired_at'],缺失交易日=', '.join(meta['missing']) or '0',日线观察='完整性合格' if meta['daily_observation_eligible'] else '未合格',ICT='关闭／分钟证据未合格'))
        else:
            rows.append(dict(证券=c,启用=e['enabled'],状态='历史数据待导入',日K=0,起始='—',截至='—',来源='未取得',取得时间='未取得',缺失交易日='未知',日线观察='未合格',ICT='关闭'))
    return rows


def render_history(archive, settings, legacy, clear):
    st.subheader('历史数据覆盖与独立导入 · v0.4.2')
    notice=st.session_state.pop('_daily_import_notice',None)
    if notice:st.success(notice)
    rows=coverage_rows(archive,settings['watchlist_entries'],legacy)
    st.caption('日K可查看 '+str(sum(r['日K']>0 for r in rows))+' / '+str(len(rows))+' 只；历史图表不是实时行情。')
    st.dataframe(pd.DataFrame(rows),hide_index=True,width='stretch')
    st.caption(BLOCK+' 新增日K不进入原ICT候选。以下列表只按覆盖日期与证券排序，不表示交易机会或收益排名。')
    eligible={e['symbol'] for e in settings['watchlist_entries'] if e['enabled']}
    daily=[r for r in archive.coverage() if r['symbol'] in eligible and r['daily_observation_eligible']]
    daily.sort(key=lambda r:r['symbol']);daily.sort(key=lambda r:r['last'],reverse=True)
    st.write('独立日K观察列表（完整性合格）：'+('、'.join(r['symbol'][3:] for r in daily) or '暂无'))
    st.caption('复权口径：工具未暴露；日线聚合时段：未确认。SIP为本次请求feed，不表示已完成供应商最终性验证。')
    if st.button('读取最新已导入历史'):
        clear();st.success('历史缓存已刷新；回到交易工作台查看日K。')
    with st.expander('逐证券增量导入供应商JSON'):
        st.caption('使用Alpaca get_stock_bars导出的完整JSON（含request与bars），或本机归档的response封装。此入口不发起网络请求。同日冲突拒绝，缺日不补值。')
        choices=[e['symbol'] for e in settings['watchlist_entries'] if not legacy.get(e['symbol'],{}).get('daily')]
        st.caption('原四ETF沿用冻结快照，此入口只导入缺少原快照的证券。')
        if not choices:return
        symbol=st.selectbox('历史导入标的',choices)
        acquired=st.text_input('数据取得时间（带时区ISO时间）',placeholder='2026-11-03T08:00:00+00:00')
        upload=st.file_uploader('供应商日K JSON',type=['json'])
        if st.button('校验并增量导入',disabled=upload is None):
            try:
                data=json.loads(upload.getvalue().decode('utf-8-sig'))
                when=data.get('acquired_at') or acquired.strip()
                if not when:raise ValueError('请填写实际数据取得时间。')
                result=archive.import_payload(data.get('response',data),symbol,when)
                clear();st.session_state['_daily_import_notice']=f"已导入{symbol}：新增{result['added']}根，累计{result['bars']}根，缺失交易日{len(result['missing'])}个。"
                st.rerun()
            except (ValueError,KeyError,TypeError,UnicodeError) as exc:
                st.error('导入拒绝：'+str(exc))
