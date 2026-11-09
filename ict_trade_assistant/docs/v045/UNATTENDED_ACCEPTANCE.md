# v0.4.5 第二阶段：无人值守包装层

状态：开发验证；未部署、未注册/启用任务、未重启8506。第一关真实新增日K和供应商最终性仍待验收。

依赖：PR #50，固定提交 `15fc7ede220edc74b861b2533c4bd5eee468954f`。该PR仍为Draft；本PR叠加其分支，不合并任何PR。现有行情、复权、EMA/ATR、ICT、发布和生命周期代码均不修改。不增加依赖。

## 已确认基线与缺口

2026-11-09只读预检核对正式目录 `C:\Users\cbcbe\TradingCodex\ict_trade_assistant_v04`：8个部署文件与#50一致；8506/8501健康200/ok；四项ICT任务定义与部署快照一致。23只证券各90根，2026-07-02至2026-11-06，共2070根，逐只QFQ/NONE/复权验证通过。

原始基线 `data/history_recovery/20261106_d495bd8/futu_qfq_20261106.sqlite3` SHA256为 `b39d76abd5993f60934ea753041aa46a468971d5b9879b3a0fa8957e64d5f3ec`。正式最后结果为UP_TO_DATE，没有新版本指针。上述是开发前只读证据，不是无人值守或新增日验收。

最终部署报告位于本机源工作树 `C:\Users\cbcbe\Documents\ChatGPT\ict_trade_assistant\.worktrees\v045-futu-daily\ict_trade_assistant\.local\deploy-v045-20261109\DEPLOYMENT_REPORT.md`。该报告保留全系统任务快照有Windows自身定义差异的审计例外，不能改称全系统不变。

原 `Start_ICT_Desk.ps1` 没有恢复完整Futu/实验路径。当前变量仅属于8506进程；重启恢复必须用独立入口读取明确配置，不能依赖父终端残留环境。本轮保留原脚本字节，不替换快捷方式，不安装持久启动项。

现有日K验证器只执行交易所收盘后2分钟检查，并明确标记 `VENDOR_FINALITY_UNVERIFIED`。Futu历史K线接口没有在已查阅文档中承诺固定最终更新时间，session参数说明也不能单独证明日K组成。因此06:30 UTC只是保守候选观测时刻，不能作为供应商最终性已证明的声明。

来源：
- https://openapi.futunn.com/futu-api-doc/quote/request-history-kline.html
- https://openapi.futunn.com/futu-api-doc/quote/get-rehab.html
- https://openapi.futunn.com/futu-api-doc/en/quote/get-global-state.html
- https://www.nyse.com/trade/hours-calendars
- https://learn.microsoft.com/en-us/windows/win32/api/taskschd/nf-taskschd-itrigger-put_startboundary
- https://learn.microsoft.com/en-us/windows/win32/api/taskschd/ne-taskschd-task_logon_type
- https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset

## 第一关真实新增日验收

本轮不执行正式更新，也不预约自动验收。未来须在单独批准的真实更新窗口执行现有按钮/引擎：

| 项目 | 成功标准/证据 |
|---|---|
| 首次候选时间 | 2026-11-10 06:30 UTC = 北京14:30 = 纽约01:30 EST；目标2026-11-09 |
| 延后核对 | 07:30 UTC再核对价格/成交量/事件；时间戳变化不算价格修订；有差异记录修订并重验 |
| 真实新增 | 23只都覆盖11月9日；沿当前起点应各91根、总2093根；禁止用合成数据替代 |
| 来源与复权 | 保存每页及manifest SHA256，完整重取QFQ/NONE/get_rehab，共同SDK、估值日、日期；沿用全部现有容差及不支持事件拒绝规则 |
| 原子发布 | 先完成独立库、验证所有证券，再原子切换current.json；记录previous、版本哈希和token回执 |
| 计算与页面 | 同一8506会话免重启显示新日期；EMA20/50、ATR14和图表与Python独立复算一致；不要求每只指标数值必然变化 |
| 回放 | 截止11月6日不包含11月9日；在同一复权基准上核对，事后QFQ不冒充当时交易价 |
| 保护 | 原历史库/旧版本/捕获哈希不变；用户库用含WAL的一致性快照逐行比对，合法页面观察追加须单列核实；不简单要求活动用户库文件哈希相同 |
| 故障/回滚 | 故障注入只在隔离副本；保留失败回执、旧指针、进程树清理、状态恢复与锁释放证据；正式库不做破坏性演练 |

稳定复查只能证明观测区间一致，不能证明永不修订。没有真实新增日，不得通过第一关；供应商最终性/日K语义不能核实时，整体仍待验收。

## 新增文件：准确7项

| 仓库内文件 | 职责 |
|---|---|
| scripts/futu_daily_runtime.py | 校验配置、固定构建/基线/8文件哈希；七项路径显式设置/删除；有界行情登录检查 |
| scripts/run_futu_daily_scheduled.py | 日历窗口、预算账本、start_update适配、token回执、整次期限 |
| scripts/start_ict_8506_v045.py | 默认仅校验；显式--start才请求8506启动，拒绝占用端口，不停止任何进程 |
| config/ict_8506_v045.example.json | 已验收路径/哈希模板，三个开关默认false，不含凭据 |
| ops/ICT_FUTU_DAILY_8506_V045.xml | 唯一新任务的禁用模板；不注册、不触发现有四项ICT任务 |
| tests/test_futu_daily_scheduled.py | 时间、恢复、隔离、失败、预算、并发、进程树和模板检查 |
| docs/v045/UNATTENDED_ACCEPTANCE.md | 本说明及验证结果 |

安装后的配置目标为 `.local/ict_8506_v045.json`，日志/预算在现有 `data/futu_history_versions_8506_v045/scheduler/`。均不提交。只有后续获批部署才复制这些文件、创建配置及决定权限；本次没有对正式目录写入。

## 调度和失败恢复合同

1. 日触发06:30 UTC（北京14:30；纽约冬01:30/夏02:30）。XML含Z，日历由现有XNYS/America/New_York处理，不硬编码美国UTC偏移。补跑仅06:30 UTC以后、纽约09:00以前；窗口外DEFERRED，顺延。无时区时间拒绝。
2. 当前版本覆盖目标日就SKIPPED，无供应商请求/新历史版本；落后才执行全量引擎，补齐所有缺日。周末/假期已经覆盖时直接跳过；同日供应商修订的主动检查继续通过现有人工按钮完成。
3. 必须三个开关全为true：unattended_enabled、real_new_day_accepted、vendor_finality_accepted。代码不自动翻转。这是运维验收声明，不是代码自行证明真实数据/最终性；没有证据不得设置。模板及任务均关闭。
4. 30秒内只检查本机OpenD行情登录qot_logined；trd_logined无需为true，不建立交易上下文、不取账户、不解锁、不替用户登录/重启OpenD。失败终止当日自动尝试，等待人工处理。
5. 经现有start_update启动原监督进程，沿用相同版本目录和update.guard锁；不直接调用run_update、不凭裸PID杀进程。调度额外锁在scheduler子目录，只保护自身账本。
6. 每目标日最多2次尝试，开始前原子记账，重启不重置。BUSY或明确已识别的抓取超时可60秒后重试一次。旧引擎只提供通用退出码的错误不猜测其可重试性；登录/权限/校验错误停止自动重试。崩溃留下RUNNING也算已消耗一次；账本损坏拒绝覆盖，需人工审核。
7. 现有完整引擎600秒期限不变，适配等待最多650秒。整次调度用现有bounded_worker/Job Object约束1500秒，关闭所属后代，最多再等待10秒清理；Windows任务外限27分钟。嵌套Job Object归属失败就停止，不降级PID终止。整次超时后不再重试。
8. 只接受本次token回执或已提交指针结果；启动成功/旧status.json不算成功。成功后重新验证当前23只归档与安全目标日一致。发布已提交、状态文件失败时仍以指针恢复结果，不撤销已提交版本。
9. 每次保存目标、次数、token、阶段/结果、前后版本、开始/完成时间和耗时；exit_code为包装层结果码，供应商子进程退出码沿用原引擎原因/日志，不捏造结构化供应商错误。引擎已有原始捕获、日志和回执继续保留。整次超时另写failure_<invocation>.json。磁盘全不可写时只能依赖退出码和已有证据，不能保证错误文件落盘；不自动删除历史证据。
10. InteractiveToken/普通权限/隐藏PowerShell/IgnoreNew/WakeToRun/StartWhenAvailable，登录后另延迟2分钟检查。仅已有用户会话可运行；锁屏可继续，冷启动尚未登录不保证运行。恢复/登录后重新计算目标和预算；OpenD未就绪记录失败，不变更其现有自启任务。硬件不能唤醒时不能承诺准点。
11. 8506不必运行；更新器只读基线并写独立版本目录。新页面启动后读取当前指针，已打开工作台沿用原15秒刷新逻辑。原始历史、用户、实验数据库不在调度器写入范围。

## 配置校验及启动恢复

开发工作树中的模板指向正式目录，因此根目录身份检查应拒绝直接用于开发工作树，避免误写正式版本。后续部署时需核实解释器仍是同一个已安装环境、全部路径/哈希、ACL与磁盘空间；不安装依赖。

模板的build_sha256取自已验收的正式部署组合，并非整个#50源码目录的构建值。部署文件必须按已验收原始字节校验，避免Git检出时LF/CRLF转换改变哈希；本轮隔离检出的futu_task.py已恢复为15fc7ed原始字节，Git内容无变化。模板8文件、正式构建和原始基线均已只读复核匹配；没有为适配工作树而改写正式验收哈希。

默认无--run/--start均只读校验配置；不创建版本目录，不联系OpenD，不启动8506。

正式目录安装后可用同一现有Python环境运行：

```powershell
& 'C:\Users\cbcbe\TradingCodex\ict_trade_assistant\.venv\Scripts\python.exe' -B 'C:\Users\cbcbe\TradingCodex\ict_trade_assistant_v04\scripts\run_futu_daily_scheduled.py' --config 'C:\Users\cbcbe\TradingCodex\ict_trade_assistant_v04\.local\ict_8506_v045.json'
& 'C:\Users\cbcbe\TradingCodex\ict_trade_assistant\.venv\Scripts\python.exe' -B 'C:\Users\cbcbe\TradingCodex\ict_trade_assistant_v04\scripts\start_ict_8506_v045.py' --config 'C:\Users\cbcbe\TradingCodex\ict_trade_assistant_v04\.local\ict_8506_v045.json'
```

独立启动入口只在额外部署/重启批准后使用--start。它移除父环境的ICT_*设置，再恢复七项已审计路径；两个null不被父终端污染，保留其他进程环境但不打印。8506端口占用一律拒绝，不关闭8501/OpenD或已有8506。启动请求返回后仍必须核对心跳创建时间、构建、七项路径与health；返回0不是服务验收完成。

## 测试与验证记录

开发前原定向48项测试通过（0失败/跳过）。新增测试使用临时库、SDK替身和受控子进程；没有调用真实OpenD，不产生真实市场结果。真实子进程恢复测试只运行输出路径环境的临时脚本，不启动网页服务。

最终验证：综合回归168通过、0失败、0跳过；随后补齐失败记录/路径别名保护，最终新增测试42通过、0失败、0跳过。原正式验收范围128项与最终新增42项去重共170项。没有删除测试或降低断言。警告为既有exchange_calendars/NumPy timedelta弃用提示，本轮不改动相关依赖。

Python AST语法检查和git diff --check通过。Windows任务计划程序NewTask仅创建内存定义，XmlText原生解析通过：Enabled=false、2个触发器、PT27M；没有调用注册接口。四项现有ICT任务再次只读导出至内存，全部定义哈希与正式部署快照一致。仅声明这四项匹配，不声称全系统任务快照完全不变。

本机隔离证据在 `.local/unattended-validation/`：pytest.xml、pytest-scheduler-final.xml、native-task-template.json、ict-tasks-unchanged.json、summary.json；不提交用户数据或日志副本。以下为命令范围，均在本隔离应用目录执行：

```powershell
& 'C:\Users\cbcbe\TradingCodex\ict_trade_assistant\.venv\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider tests/test_futu_daily_scheduled.py --junitxml=.local/unattended-validation/pytest-scheduler-final.xml
& 'C:\Users\cbcbe\TradingCodex\ict_trade_assistant\.venv\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider tests/test_daily_update_v043.py tests/test_decision_first.py tests/test_deployment_protection.py tests/test_experiment_v044.py tests/test_futu_daily.py tests/test_futu_task_lifecycle.py tests/test_futu_update_v045.py tests/test_history_v042.py tests/test_v0441.py tests/test_v04_live_gate.py tests/test_futu_daily_scheduled.py --junitxml=.local/unattended-validation/pytest.xml
git diff --check
```

现有独立发布、回滚、EMA/ATR、回放截断、页面和实时ICT门禁测试保留原样。正式计划任务触发、唤醒、登录补跑和真实新增日均需后续独立授权验收；本地模拟通过不能代替。

## 回滚与审批边界

开发交付只含7个新增文件和Draft PR。部署、重启、注册/启用任务、权限调整与PR合并均不包含在本次开发批准内。

若后续获批部署失败，先停用仅新增任务，确认其所属更新已结束；移除/恢复本轮新增入口和配置，回到原手工启动方式并完整恢复既有七项环境。不修改原启动脚本，不覆盖用户/实验库。

若新历史版本需回滚，确认无活动更新并取得同一版本目录OS锁，完整验证previous，再调用现有rollback原子回退指针。现有rollback函数本身不加锁，操作入口必须持锁；本轮不执行正式回滚。保留新旧库、捕获、回执及预算记录，不能以回滚为由覆盖原始历史。
