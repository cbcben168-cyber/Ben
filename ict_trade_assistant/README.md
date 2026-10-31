# ICT Trading Desk MVP v0.1

独立 Windows 本地只读看板。Python 3.11/3.12；建议 3.12。双击 **Start_ICT_Desk.cmd**，首次联网安装依赖，随后自动打开 http://127.0.0.1:8501 。OpenD 请自行登录并在本机 11111 端口开启行情服务；不需要解锁交易。启动脚本遇到占用端口会明确退出，不终止他人进程。

## 使用
1. 工作台选择 SPY/QQQ/IWM/SOXX；真实权限和时间检查通过才显示 AVAILABLE。
2. 设置页修改名单、距离（bps）、刷新（30–3600 秒）、图层；保存即写审计。
3. 设置区域上下限、方向与失效价；工作台在 RTH 新鲜报价上记录接近/到达/失效事件，记录原因。
4. 事件页添加人工备注；SOP 页核对操作流程；预留页清楚标识未实现。
5. 停止服务：根据启动窗口输出的 PID 执行 `Stop-Process -Id <PID>`。

## 数据契约
- 只连接 `OpenQuoteContext`，没有交易账户连接或任何订单接口。
- Futu 美股 time_key/data_date/data_time 解释为 America/New_York；拒绝 DST 歧义/不存在时间，不使用北京时间常量。
- 使用 exchange_calendars XNYS，交易日 09:30 开盘，正常 16:00，假日/提前收盘按日历。日历范围外失败，不猜测。
- RTH/PRE/AFTER/NIGHT/UNKNOWN 分开存储；NIGHT 为 Futu 时钟桶，不证明 Nasdaq 计划夜盘已生效。提前收盘扩展时段未验证归 UNKNOWN。
- 请求最近 7 天 ALL 1M、120 天原生不复权日线。每次分页最多 15 页，完整性另外标识；缺分钟不补。
- 1H/4H 由 RTH 完整分钟重建，09:30 锚定；4H 正常日最后柱 150 分钟，提前收盘实际时长显示在复核表。不是原生 4H。
- OR 5/15/30 需所有对应分钟；最新两分钟隔离。前日高低需前一交易日全部 RTH 分钟。PRE/NIGHT 同样完整性要求严格，无交易分钟也不插值，故可能不可用。
- 这些是观测范围，不是供应商最终性证明。所有柱与关键价标 VENDOR_FINALITY_UNVERIFIED；无自动 MSS/FVG/Sweep 确认。
- 报价权限仅 LV1/LV2/LV3 为候选；未知/其他为 UNAVAILABLE；年龄 >90 秒为 STALE；未来时间/服务器时钟偏差 >5秒禁用。SF 等权限不冒充全市场实时权限。
- RTH last_price 不用于盘前/盘后/夜盘提醒，因为独立扩展时段更新时间未验证。闭市价格可展示但不会宣称实时。
- 提醒每 ET 日/标的/区域/距离/状态去重一次；无弹窗、声音或外部发送，事件留在本地。
- SQLite `data/desk.sqlite3` 保存行情、参数、审计、事件、备注和关键价。原始返回的用户身份/敏感字段不保存。缓存断线时不回放为实时。

## 验证与开发
```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m streamlit run app.py
```
范围见 MVP_SCOPE.md，布局见 UI_LAYOUT.md，进度见 PROGRESS.md，验收见 ACCEPTANCE.md。
这是新独立目录，无旧 ICT 项目修改。无回测、无自动下单、无收益保证。

官方接口依据：
- https://openapi.futunn.com/futu-api-doc/quote/request-history-kline.html
- https://openapi.futunn.com/futu-api-doc/quote/get-stock-quote.html
- https://www.nyse.com/trade/hours-calendars
- https://nasdaqtrader.com/Trader.aspx?id=Calendar


## 简体中文界面规范
界面固定文案与术语解释集中在 `desk/i18n.py`。新增页面优先复用该目录；内部状态值、行情接口及数据库字段保持原样，只在展示时转换。用户输入原文不自动翻译。

常用状态：AVAILABLE 为行情数据可用；STALE 为行情数据已过期；UNAVAILABLE 为行情数据不可用；INCONSISTENT 为行情数据不一致；UNKNOWN 为资料不足；PARTIAL 为部分完成；PENDING_VISUAL_ACCEPTANCE 为等待视觉验收。任何数据阻断都不能提示新的入场审查。

常用术语：RTH 为常规交易时段，PRE 为盘前，AFTER 为盘后，NIGHT 为供应商夜盘时钟桶；PDH/PDL 为前日高低点，PWH/PWL 为前周高低点；Sweep/Reclaim 为流动性扫掠与价格收复，MSS 为市场结构转变，FVG/CE 为公允价值缺口及其中点；SOP 为标准操作流程；R/R 为风险回报比；FORMING 为正在形成，CONFIRMED 为已确认；NOT_VERIFIED 为尚未验证。

当前 UI V2 仍为部分完成，详见 UI_V2_ACCEPTANCE.md。本地化完成不代表行情资格或双屏布局验收通过。


## UI V2 人工计划与价格提醒
首页下方展开“备注与人工计划编辑”，为当前标的填写方向、策略版本、入场区、失效价、目标区和备注后保存。未填写完整合法价格时不会生成风险回报数字。保存后点击“载入最新计划”，从“编辑计划”选择计划编号即可修改或取消；每次操作都保留版本，其他窗口已更新的旧版本提交会被拒绝。取消的是本地计划，不涉及订单，也不删除独立人工关注区域。

前日、前周、开盘区间和人工计划图层可分别关闭。前周使用上一已结束日历周的全部实际常规交易日；缺日不补值。自动结构事件尚待验证，不根据人工计划宣称信号确认或已成交。自动刷新只更新行情区域，指定场景已验证保留表单输入；复杂编辑仍建议关闭自动刷新。

浏览器截图与验收记录见 UI_V2_ACCEPTANCE.md；Windows原生缩放仍待本机确认。离线验收入口 scripts/ui_acceptance_fixture.py 使用合成行情及独立测试数据库，不能用于交易；日常只打开 http://127.0.0.1:8501 。


## 稳定性诊断与恢复
应用使用局部刷新，首次加载后按设置的行情周期更新。两个窗口可独立选股，后台共享快照。读取失败时保留历史图表并显示STALE（行情过期），不能据此进行新的入场审查。自动恢复有次数上限；提示暂停后，在设置与诊断中点击“立即刷新行情”才能重置重试。

不要重复启动8501服务。代码更新后需正常停止并重新启动以载入完整版本，运行中不自动监视源文件。故障发生时保留data/runtime.json、stability.log、fatal.log及streamlit-error.log；不得删除数据库来尝试恢复。详细裁定、真实周期核对、回滚位置与未完成项见STABILITY_ACCEPTANCE.md。本轮未宣称长期运行已经根治。
