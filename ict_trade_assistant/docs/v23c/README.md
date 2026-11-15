# QQQ V23C提醒：隔离实现与手动验收

状态：开发版，尚未完成Pine云端编译、手机实收或真实TradingView到工作台的端到端验收。未部署正式8506，未修改常驻任务、原用户计划、实验组合、行情验证器或ICT门禁。

## 当前可以做什么

- 开发看板 `http://127.0.0.1:8531/`：主页的QQQ V23C独立卡及“其他策略”详情，显示请求、状态与模拟成交。
- 本机接收器 `127.0.0.1:8532`：仅回环监听、Bearer认证、独立SQLite、去重、过期记录及输入校验。当前启动参数为 `--simulation`，所有记录强制标注“隔离样本”，不能当成真实策略信号。
- TradingView手机推送可独立于本机配置；电脑关闭时本地看板不能同步。公网HTTPS接入、缓存补收和正式接收模式未部署，不能直接填写本机8531/8532作为TradingView Webhook。

本程序不运行Pine、不用原Futu日K近似重建V23C，也不将模型股数当成用户真实持仓。收到外部研究消息不代表有真实订单、真实成交或ICT交易许可。

## 手动操作：编译与图表

1. 用文本编辑器打开 `strategies/v23c/QQQAV23C_P0_Alerts_V1.pine`，复制完整内容。原始文件另存于 `strategies/v23c/original.pine`，不要覆盖原策略。
2. 在TradingView中新建独立策略脚本或打开明确的副本。上次桌面操作已创建同名草稿，但没有可靠验证代码导入，所以不能仅凭名称判断已安装提醒代码。
3. 先单击Pine编辑器**代码正文**，确认出现编辑光标，再Ctrl+A、Ctrl+V。不要在K线画布上粘贴。保存独立文件，再“Add to chart / 添加到图表”。没有编译错误才继续；如有错误，保留第一条错误文字与行号，先不创建警报。
4. 图表明确选择 `NASDAQ:QQQ`、`1D`、普通蜡烛、Regular trading hours / 正常交易时段。之前看到的现有V23C图是1小时图，原策略在该周期不会按日线调仓。
5. 复权和策略属性沿用已验收口径；不在接入提醒时改变A/B开关、资金、手续费或订单执行设置，不开启逐tick重算、成交后重算或同根收盘成交。
6. 策略设置 → Inputs → `V23C Research Alerts`：开启 `Enable research alerts`；建议保留 `Send daily HOLD status`，这样没有调仓时也可收到日线状态；参数标签先保持 `P0_DEFAULT`。出现这组设置才说明图上加载的是提醒副本。

## 手动操作：先开收盘提醒

1. 点击Alert / 警报。
2. Condition选择新加的策略实例，事件选 `alert() function calls only`（仅alert()函数调用）。这条警报是收盘调仓请求和每日状态，不是模拟成交。
3. Notifications勾选 `Notify on App`。手机登录同一TradingView账户，并在手机系统中允许该App通知；可同时开启声音。
4. 名称建议 `QQQ V23C 1D 收盘提醒`，核对到期时间，再创建并确认警报处于运行状态。消息由Pine的alert()自动生成。
5. 修改脚本、参数、证券或周期后，重新创建警报；旧警报使用创建时的快照，不会自动跟随修改。
6. 警报只在未来真实日K收盘迭代触发，不因导入历史、回测或回放补发。手机实际收到、且警报日志与该条信号一致后，才记为手机实收通过。今天为周日，不能因没有新日K提醒而认定通道故障。

提醒里的 `REQUEST` 是加仓/减仓/清仓请求，`STATE/HOLD` 是本次无需调仓。REC图标只是恢复加仓条件，不能直接当成实际调仓请求。原策略保持下一可用交易时点的模型成交约定，收盘收到请求不等于已经成交。

## 可选：单独记录模拟成交

再建立一条策略警报，事件选 `Order fills only`（仅订单成交），消息框完整粘贴 `strategies/v23c/fill_message.txt`，也勾选Notify on App。这是TradingView撮合模拟器的事件，仍不是用户券商成交。

模板中的 `{{plot_6}}` 对应原P0脚本第7个输出，即A/B执行模式；配置标签若改变，要同步修改模板。模板只有经过TradingView占位符替换后才是有效JSON，不能将未替换模板直接当真实消息发送。

## 手动操作：页面验收

1. 打开8531，点击主页“查看V23C提醒与记录”，或在侧栏选择“其他策略”。
2. 应能看到“QQQ V23C · 独立策略提醒”、独立的“调仓请求与日线状态”和“模拟成交”区域。
3. 当前5条记录都是隔离样本，价格和仓位是测试值；其中的“清仓请求”不是今天真实QQQ信号。
4. 刷新页面应保留相同记录，重复同一消息不增加第二条；模拟成交不得改写为真实账户成交。
5. 出现“手机推送尚未验收”属于当前真实状态。你在TradingView开启手机推送后，也不会自动打通工作台同步：真实上报入口和接收器正式模式仍待单独部署。

当前工作台验收不能替代真实端到端验收：下一条真实信号需对照TradingView警报日志、手机实际消息、独立接收时间和数据库记录。四者对应后才可确认链路接通。

## 实现与保护

- 原Pine SHA256：`bb098c7fa0b5f88299df2f154a30edb2e80a6e0b25e0331cb61c7c9b4e8778e6`。59225字节完整保留在提醒副本前部，新内容仅追加。原订单调用和A/B选项未改。
- 接收器校验证券、1D/RTH、纽约交易日边界、提前收盘/DST、确认与实时标识、未来时间、有限数值、0–135%模型目标、版本及字段集合；超过5分钟的延迟消息仅留档。这个传输窗口与ICT的90秒/2分钟门禁无关。
- 消息没有外部行情最终性认证，`external_finality=UNVERIFIED`，输入标签不是参数一致性证明；原策略缺失外部资料时的默认行为未被重写。消息和页面均保持研究用途。
- 接收器不会打开真实账户或订单接口。密钥只在被Git忽略的.env，不进入Pine、消息或访问日志。未来公网中继需独立认证并注入本机Bearer，不能把这个密钥写进TradingView代码或警报正文。
- 实际本机HTTP验收：5条模拟记录、重复幂等、未授权拒绝；没有真实TradingView消息或手机送达证据。
- 158个原文件、冻结计算、原始Pine和归档文件哈希保护通过，正式用户库11表及实验库1表/schema保持一致。

## 测试与交付状态

完整pytest：331项，329通过，2项既有失败，未修改原断言或超时：

- `tests/test_portrait_layout.py::test_four_unique_candidates_not_replaced_by_empty_layout`：旧断言期待4个候选，基线为5个。
- `tests/test_ui.py::test_navigation_settings_notes`：旧控件操作没有把距离参数10改为25。

本轮新增30项信号/HTTP/独立页面/Pine字节保护测试均通过；加入配置回归的定向运行40项通过（不含后来添加的2项Pine保护测试，它们已在完整运行中通过）。AppTest不等于真实浏览器、Pine编译或手机实收。

主要运行命令：`git fetch origin`；从b243e87建立 `codex/v23c-desk-alerts` 工作树；`python -B -X utf8 -m pytest -q --tb=short --disable-warnings`；`Start_ICT_Desk.ps1 -Port 8531 -Config <隔离配置> -NoBrowser`；`python scripts/run_v23c_receiver.py --port 8532 --db <独立数据库> --simulation`。公网、正式8506、计划任务均未修改。TradingView桌面操作被用户Esc中断，未创建运行警报。

后续部署必须逐项核实Pine编译、原模型计算对账、手机实收、真实接收来源与持久运行。当前分支只可作为待验收草稿，不宣称正式可交易或长期在线。

官方操作依据：[Pine Alerts](https://www.tradingview.com/pine-script-docs/concepts/alerts/)、[创建警报与手机通知](https://www.tradingview.com/support/solutions/43000595315-how-to-set-up-alerts/)、[Webhook接入要求](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/)。
