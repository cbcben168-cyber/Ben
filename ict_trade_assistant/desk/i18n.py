"""简体中文展示目录；只在显示边界转换，不改写行情或持久化原值。"""
import re

TERMS = {
    'MARKET_OBSERVATION': '市场价格观察', 'SYSTEM_HEALTH': '系统健康诊断',
    'VENDOR_FINALITY_UNVERIFIED': '供应商最终完成状态尚未验证',
    'UNAVAILABLE_INCOMPLETE': '数据不完整，暂不可用',
    'OBSERVED_COMPLETE': '观测范围完整（不代表供应商最终确认）',
    'PENDING_VISUAL_ACCEPTANCE': '等待视觉验收',
    'NOT_IMPLEMENTED': '尚未实现', 'NOT VERIFIED': '尚未验证',
    'NOT_VERIFIED': '尚未验证', 'PARTIAL': '部分完成',
    'DATA_BLOCKED': '数据异常，已阻止新入场审查',
    'NO NEW ACTION': '暂停新增操作', 'CANCEL SETUP': '取消当前交易计划',
    'CONFIRMED': '已确认', 'FORMING': '正在形成，尚未确认',
    'INVALIDATED': '当前交易计划已失效',
    'INCONSISTENT': '行情数据不一致', 'DISCONNECTED': '行情服务已断线',
    'UNAVAILABLE': '行情数据不可用', 'AVAILABLE': '行情数据可用',
    'STALE': '行情数据已过期', 'UNKNOWN': '未知，资料不足',
    'WAIT': '等待确认', 'LONG': '潜在做多', 'SHORT': '潜在做空',
    'DATA_HEALTH': '数据健康提醒', 'ALERT': '价格提醒', 'NOTE': '人工备注',
    'Sweep': '流动性扫掠', 'Reclaim': '价格收复', 'MSS': '市场结构转变',
    'FVG': '公允价值缺口', 'CE': '缺口中点', 'SOP': '标准操作流程',
    'PDH': '前日高点', 'PDL': '前日低点', 'PWH': '前周高点', 'PWL': '前周低点',
    'RTH': '常规交易时段', 'PRE': '盘前时段', 'AFTER': '盘后时段',
    'NIGHT': '夜盘时段', 'CLOSED': '休市', 'HOLIDAY': '假日休市',
    'OR': '开盘区间', 'USD': '美元', 'bps': '基点',
    'FUTU_OPEND': '富途 OpenD 行情', 'DERIVED_FROM_FUTU_1M': '由富途一分钟数据聚合',
    'LV1': '一级行情权限（LV1）', 'LV2': '二级行情权限（LV2）', 'LV3': '三级行情权限（LV3）',
}
FIELDS = dict(quality='数据状态', reason='原因', price='价格', quote_at='报价时间',
 received_at='接收时间', age_seconds='报价年龄（秒）', session='交易时段',
 source='来源', right='行情权限', server_clock_skew_seconds='服务端时钟偏差（秒）',
 low='下限', high='上限', invalid='失效价', direction='方向', stage='阶段',
 status='状态', start='开始时间', end='结束时间', rows='记录数', expected='预期记录数',
 finality='最终完成状态', id='记录编号', at='记录时间', kind='事件类型', symbol='标的',
 payload='详细内容', dedupe='去重标识', key='参数名', old='原值', new='新值',
 watchlist='观察名单', distance_bps='接近距离（基点）', refresh_seconds='刷新间隔（秒）',
 layers='价格图层', zones='人工关注区域', health='数据健康', zone='人工关注区域',
 notes='备注', FUTU_OPEND='富途 OpenD')
_PATTERN = re.compile(r'(?<![A-Za-z0-9_])('+'|'.join(re.escape(k) for k in sorted(TERMS,key=len,reverse=True))+r')(?![A-Za-z0-9_])')

def zh(value):
    """仅转换系统展示文本；用户输入与数据库原值保留。"""
    return _PATTERN.sub(lambda m: TERMS[m.group()], str(value))

def details(value):
    if isinstance(value, dict):
        return {FIELDS.get(k, k): details(v) for k,v in value.items()}
    if isinstance(value, list):
        return [details(v) for v in value]
    return zh(value) if isinstance(value,str) else value

def table(frame):
    frame = frame.copy()
    for col in frame.columns:
        if col in {'kind','key'}:
            frame[col] = frame[col].map(lambda v: FIELDS.get(v,zh(v)))
    return frame.rename(columns=FIELDS)

# 页面固定文案集中于此；新增页面继续使用此目录。
TEXT = {}

TEXT.update({'文案1': '◈ ICT 交易工作台', '文案2': '最小可用版本 v0.1 · 只读观察工作台', '文案3': '导航', '文案4': '观察标的', '文案5': '设置与审计', '文案6': '人工关注区域', '文案7': '参数变更留痕', '文案8': '观察名单（逗号分隔，美股代码）', '文案9': '接近距离 / 基点', '文案10': '刷新间隔 / 秒', '文案11': '显示关键价格与区域图层', '文案12': '保存参数', '文案13': '事件与人工备注', '文案14': '区域下限（美元）', '文案15': '区域上限（美元）', '文案16': '观察方向', '文案17': '失效价格（美元）（0 表示不设置）', '文案18': '人工 SOP 阶段', '文案19': '保存区域', '文案20': '删除该标的区域', '文案21': '观察理由 / 复核记录（请勿输入密码密钥）', '文案22': '操作 SOP / 项目进度', '文案23': '不提供盈利 Edge、自动交易或自动形态确认。Nasdaq 计划新增夜盘未作为已生效交易时段。', '文案24': '尚未实现 · 仅预留导航与接口位置', '文案25': '本阶段未实现此功能；没有交易账户连接、交易记录导入、期权分析或下单。', '文案26': '请填写 1–20 个有效美股代码。', '文案27': '记录备注', '文案28': '已保存到本地 SQLite。', '文案29': '区域须为正值且有序；做多失效价低于区域，做空失效价高于区域。', '文案30': '设置与数据诊断', '文案31': '参数与人工关注区：侧栏 → 设置与审计。自动刷新默认关闭，避免打断编辑。', '文案32': '自动刷新行情（编辑备注时请关闭）', '文案33': '立即刷新行情', '文案34': '独立窗口观察标的', '文案35': '行情诊断明细', '文案36': '前五名候选', '文案37': '排序', '文案38': '周期', '文案39': '关键价格图层', '文案40': '富途行情 · 纽约交易所时间（America/New_York） · 不复权常规时段 · 四小时由分钟数据聚合 · 供应商最终完成状态尚未验证', '文案41': '前日高低价', '文案42': '前周高低价、流动性扫掠与收复、市场结构转变、公允价值缺口与中点、目标：未知或未形成；不自动确认。', '文案43': '下一触发区：', '文案44': '候选入场：未形成', '文案45': '失效价：', '文案46': '做多时跌破 / 做空时突破人工失效价；不代表已成交。', '文案47': '风险回报比（R/R）：待评估 · 未定义确认入场及目标', '文案48': '标准操作流程检查表', '文案49': '当前持仓 / 人工计划', '文案50': '未连接交易记录 / 尚无已确认持仓数据', '文案51': '无有效候选：需要新鲜报价及人工关注区域。', '文案52': '当前观察标的已离开前五名候选；保留选择。', '文案53': '行情数据不可用：没有该周期完整真实数据。', '文案54': '人工备注', '文案55': '保存备注', '文案56': '尚无事件记录', '文案57': '已持久保存', '文案58': '已读', '文案59': '确认已读'})

TERMS.update({'PREVIOUS_RTH': '前一常规交易日', 'get_stock_quote': '供应商报价接口',
 'last_price': '最新成交报价', 'OR_5': '开盘五分钟区间', 'OR_15': '开盘十五分钟区间',
 'OR_30': '开盘三十分钟区间'})
_PATTERN = re.compile(r'(?<![A-Za-z0-9_])('+'|'.join(re.escape(k) for k in sorted(TERMS,key=len,reverse=True))+r')(?![A-Za-z0-9_])')

TERMS.update({'ACTIVE':'人工计划启用中','CANCELLED':'人工计划已取消','PLAN':'人工计划变更','PLAN_ALERT':'人工计划价格提醒','FUTU_OPEND_NATIVE_DAY_RTH':'富途原生日线，常规交易时段'})
FIELDS.update(plan_id='计划编号',version='版本',plan_version='计划版本',updated_at='最近修改时间',created_at='建立时间',strategy_version='策略版本',target_low='目标下限',target_high='目标上限',memo='计划备注',PREVIOUS_WEEK='上一完整交易周',PREVIOUS_RTH='前一常规交易日',OR_5='开盘五分钟区间',OR_15='开盘十五分钟区间',OR_30='开盘三十分钟区间')
_PATTERN = re.compile(r'(?<![A-Za-z0-9_])('+'|'.join(re.escape(k) for k in sorted(TERMS,key=len,reverse=True))+r')(?![A-Za-z0-9_])')

FIELDS.update(loading='行情加载中')

TEXT.update({
 '图层控制':'价格图层与说明',
 '价格线说明':'价格线名称与数值可悬停查看；图例收起以优先保留 K 线绘图区。',
 '图表来源摘要':'富途 · 纽约常规交易时段 · 供应商最终完成状态尚未验证',
 'SOP详情':'SOP 详细检查与评估依据',
 'RR说明':'按最不利入场端点及最近目标计算，不含费用和滑点；仅是人工计划比率，不代表信号已确认。',
 '备注说明':'在首页下方“备注与人工计划编辑”保存或修改。'
})
