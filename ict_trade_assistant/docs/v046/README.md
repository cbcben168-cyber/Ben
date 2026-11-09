# ICT Trading Desk v0.4.6 隔离验收

> **部署前最终修订：** 独立周期截止日期、过期状态及价格尺度提示已补充，见[最终部署报告](time-consistency/README.md)。部署应使用其中的**9文件清单**，下文8文件清单仅保留为首轮验收记录。

**隔离开发和验证完成；8506未部署、未重启，PR未合并，实时ICT资格未开放。**

基线固定为PR #50的`15fc7ede220edc74b861b2533c4bd5eee468954f`；开发分支`codex/ict-v046-history-workbench`。没有引入PR #51或无人值守包装层。`git fetch origin`只同步远端引用；遵从固定基线要求，没有把其他分支合入开发分支。

## 根因与结果

| 问题 | 根因 | 修复结果 |
|---|---|---|
| 1H空白 | 选择Futu日K时，来源选择器清空minute；页面继续从minute聚合1H | 新增独立原生K_60M归档和适配器，只放入futu_hourly，不冒充minute。五只指定证券均能显示630根真实K线及1H EMA |
| 观察区和目标长期暂无 | 旧行动卡只接收人工计划或合格ICT结构；日K参考价格与交易资格混在同一展示路径 | 分开显示历史参考价、用户原价计划、合格交易目标。日K参考价独立于实时门禁；不制造目标或止损 |
| 只有5只 | render_home硬编码切片前5只 | 默认已启用名单前15只；会话内可按加入顺序自选。横屏5×3，竖屏3×5，不保存名单或排序 |

顶部提供模式、日期、周期和日K来源；因子区仍折叠。四个主要区块和原深色风格保留。卡片中的“查看图表”同时切换主图、指标、区域和详情。历史参考价、人工计划和实时资格使用不同标签。价格显示保留原始有效精度。

## 真实OpenD数据

正式隔离捕获使用既有项目Python环境、Futu SDK **10.12.7208**。先查权限与历史额度：美股LV3，已用27、剩余273，23只均在既有额度名单中，新证券需求0。最初小样本预检使用全局SDK 10.11.7108；随后改用现有项目环境，没有升级依赖。

只调用行情查询：原生K_60M/RTH/QFQ及NONE、同批K_DAY用于价格与复权校验、get_rehab；SMH的K_1M只用于离线边界核对。不订阅、不查询交易账户、不下单。每次最多250根，实际60M分页250+250+130，保留逐页返回、取得时间、原始记录及逐文件SHA256。限频间隔0.6秒。[官方接口与分页说明](https://openapi.futunn.com/futu-api-doc/quote/request-history-kline.html)。

所有23只实际取得范围均为2026-07-02至2026-11-06，90个连续交易日、每只630根；原始QFQ/NONE均保留。**20只通过价格、时间和复权验收；3只虽有资料和权限，价格跨周期校验未通过，页面拒绝作为合格1H。**

| 证券 | 原生60M取得／分页 | 1H验收 |
|---|---|---|
| SPY | 630／完整 | PASS |
| QQQ | 630／完整 | PASS |
| IWM | 630／完整 | PASS |
| SOXX | 630／完整 | PASS，含三拆一复权核验 |
| SMH | 630／完整 | PASS |
| VOO | 630／完整 | PASS |
| IVV | 630／完整 | PASS |
| VTI | 630／完整 | PASS |
| VEA | 630／完整 | UNAVAILABLE：11月6日low，60M汇总67.53，日K67.525 |
| VUG | 630／完整 | PASS |
| IEFA | 630／完整 | UNAVAILABLE：11月3日high，60M汇总96.7785，日K96.79 |
| VTV | 630／完整 | PASS |
| SPYM | 630／完整 | PASS |
| BND | 630／完整 | UNAVAILABLE：9月30日QFQ low，60M汇总69.541434618，日K69.475606561 |
| VXUS | 630／完整 | PASS |
| IEMG | 630／完整 | PASS |
| VGT | 630／完整 | PASS |
| GLD | 630／完整 | PASS |
| AGG | 630／完整 | PASS |
| IWF | 630／完整 | PASS |
| IJH | 630／完整 | PASS |
| VWO | 630／完整 | PASS |
| XLK | 630／完整 | PASS |

三只差异同时出现在NONE资料，未按四舍五入放宽门槛，原因未裁定。逐项见[价格差异](reconciliation-differences.json)。失败时显示“尚无已验收1小时历史资料”及原因，并提供“切换至日K”；日K和日K参考区继续可用。

## 时间、复权与完整性

实际Futu美股60M和1M使用**纽约结束标签**。适配器验证完整的交易日网格后，保留原始标签，另生成UTC开始、结束、duration_minutes和complete；不移动OHLC，也不插值。正常日09:30–10:30起，每日最后15:30–16:00为30分钟；提前收盘日最后12:30–13:00为30分钟。

SMH两组独立原始探针：2025-11-28提前收盘日210根1M、4根60M；2026-11-06正常日390根1M、7根60M。全部11根60M的OHLC与对应1M聚合一致，开始／结束及1M覆盖逐根通过。DST前后UTC偏移及提前收盘网格有独立pytest。1M探针只留在本轮隔离证据目录，不进入原分钟库或ICT扫描。

成交量不能被描述为跨周期完全一致：正常日1M汇总相对原生60M逐柱差异为+55、-29、-30、-29、-31、-28、+25股；原生日K量与60M汇总也有差异，原因未裁定。保留各自原值，不替换。价格、完整时间网格及同周期QFQ/NONE复权量仍检查；EMA、ATR不使用成交量。完整表示已结束的预定时间区间且覆盖完整，供应商最终性仍标注`VENDOR_FINALITY_UNVERIFIED`。

每个1H OHLC与同日已独立核验的QFQ/NONE日K复权比例相符；同批日K通过原有FutuDaily验证器，以NONE及供应商事件独立重建复权。归档按批次固定估值日，读时复验SHA256及源数据，拒绝缺柱、重复、错序、非法价格或未来取得时间。原始捕获和重新验证后的版本分别保留，不改旧版。

`market_state.py`及指标定义未改：至少50根连续已完成同源K线，原50根首收盘初始化EMA、原ATR定义和2分钟隔离全部沿用。1H直接使用合格原生60M；不再次按分钟聚合。逐只数值及50个EMA端点末值见[真实资料计算证据](data-evidence.json)。SMH 1H最新收盘463.96，EMA20=474.23055851221784，EMA50=500.88149000151896，ATR14=12.217085714285721；仅为截至11月6日的历史描述。

回放在计算前截断到各柱结束+2分钟；未完成柱、右侧确认尚未发生的摆动点和未来保存的计划不进入对应计算。QFQ仍明确标注为事后前复权，含取得时已生效的后续复权，不冒充历史当时可交易价格或策略回测收益。

## 价格区域证据与边界

最新模式使用实际纽约参考时点，回放使用所选时点。前交易日指分析日之前的交易日；前一完整周指分析日所在周之前的完整纽约交易周；20日区间取该时点最近20个已完成交易日。每项附起止日期、方法、来源、估值日和capture SHA。

本次最新模式参考时点为2026-11-09纽约，SMH使用受保护的同一批`FUTU_OPEND/K_DAY/RTH/QFQ`、估值日2026-11-08：

| 参考区域 | 已完成数据日期 | 低／高 |
|---|---|---|
| 前交易日 | 2026-11-06 | 456.435／476.2499 |
| 前一完整交易周 | 2026-11-02至11-06 | 445.59／532.76 |
| 最近20个已完成交易日 | 2026-10-12至11-06 | 445.59／598.445 |

这些是历史观察范围，不是止损或盈利目标。来源capture SHA为`169b7203373df81c89b44999cf244f69fa2da85f6b41eb681b4162c8fe693a4d`。其余22只及具体逐项方法均在data-evidence.json。

已实现左右各2根完整1H柱才确认的摆动高低参考，并测试右侧第2柱完成前不泄漏。本次1H估值日为11月9日，受保护日K估值日为11月8日，因此**当前不混合显示1H结构参考位**，页面证据中明确列出估值日不同；日K三个区域独立显示。没有为了显示更多价格而重标估值日或改动已验收日K。

用户计划始终显示实际保存的原价、原始USER_MANUAL来源、版本、保存时间和方向。QFQ尺度未核实时不叠加，也不计算可执行风险回报；选择原日K来源而主图仍用QFQ 1H时同样阻断。当前计划表缺少经核实周期和有效时间契约，行动卡明确列出缺失项，合格交易目标维持未具备条件。没有自动生成目标1、目标2、止损或交易许可。

## 浏览器与测试

最终相关pytest共**199个不重复用例通过，0失败、0跳过**。广泛定向组197项通过；时点／尺度修改后相关59项复跑通过；最后显示精度修改后v0.4.6全部16项再次通过，另有会话排序单测1项记录；这些组有重叠，不按执行次数重复计数。XML及测试集合见[部署清单](deployment-manifest.json)。compileall和git diff --check通过，未删除测试或降低断言。

浏览器[40项检查](browser-acceptance.json)通过，五只指定证券逐只匹配独立Python精确EMA与收盘价，等待旧Plotly节点销毁后才计数；[15张真实卡片](browser-cards.json)全部点击通过，证券、主图收盘、右侧区域和交易锁同步。会话内调整、顺序、少于15只、重新打开不永久保存均有AppTest。

| 截图 | 真实浏览器视口及缩放 |
|---|---|
| 横屏主图与价格卡（本地screenshots/landscape-main.png） | 2560×1440，DPR=1，scale=1，CSS zoom=1 |
| [横屏全部15卡](screenshots/landscape-15-cards.png) | 上述视口中的完整卡片区域裁图，5×3 |
| 竖屏主图与价格卡（本地screenshots/portrait-main.png） | 1440×2560，DPR=1，scale=1，CSS zoom=1 |
| [竖屏全部15卡](screenshots/portrait-15-cards.png) | 上述视口中的完整卡片区域裁图，3×5 |

两种视口主图与右侧并排，无横向溢出、无Python异常，因子区保持折叠。卡片区允许正常纵向滚动，没有把裁图尺寸冒充完整视口。

两张完整主视图含用户实际人工计划价格，仅保留本地并加入本目录.gitignore；不上传到公共PR。两张15卡片截图只含历史市场资料，可随PR审查。全部四张本地截图均有SHA256记录。

## 数据和系统保护

[保护结果](protection-final.json)：正式8506的55个源码文件及28个原历史文件SHA256保持不变；用户库全部11张表和schema完全一致，实验组合表完全一致；隔离浏览器副本中的计划、设置、备注和实验组合也未改。11个冻结模块与固定提交内容一致（Git换行规范化比较），没有修改ICT规则、90秒报价门禁、2分钟隔离或实时资格锁。

[进程记录](services.json)：8501 PID19544、8506 PID63264、OpenD PID22236的创建时间均早于本任务，未重启。[任务快照](tasks-comparison.json)：隔离验收后段的231项任务定义前后完全一致；该快照不是整个任务最开始的快照，不扩张声称覆盖完整工作时段。本轮任务API均为读取／导出定义哈希，没有注册、修改或触发任务。PR #51保持未接入。

## 修改文件

完整逐文件列表见[CHANGED_FILES.md](CHANGED_FILES.md)。本任务8526预览与独立浏览器已在验收后停止。

运行候选8文件：`app.py`、`desk/dashboard_cards.py`、`desk/decision_home.py`、`desk/experiment_ui.py`、`desk/workspace.py`、新增`desk/futu_hourly.py`、新增`desk/historical_prices.py`、`scripts/v04_history_fixture.py`。

新增操作／验证工具：`scripts/capture_futu_hourly.py`、`scripts/verify_futu_hourly.py`、`scripts/verify_v046_evidence.py`、`scripts/v046_browser_check.js`、`scripts/v046_card_check.js`。测试：新增`tests/test_v046.py`；`tests/test_v0441.py`只把旧5只标题断言改为本任务要求的15只标题，其他断言保留。另新增本目录文档、JSON、XML及4张截图。

## 8506部署清单与回滚准备（尚未执行）

精确8个运行文件、3个可选手工操作工具及独立数据目录逐文件SHA256见[deployment-manifest.json](deployment-manifest.json)。目前数据在本开发工作树`.local/v046/hourly_20261109_verified`，约17MB；原始失败版本在同级`hourly_20261109_v1`，边界探针在`boundary-probes`。不把这些资料写入原日K或分钟库。

未来单独获批部署时：先复核8506身份并备份原8路径的存在状态及字节；在线备份用户和实验库仅作保护证据；按清单复制8文件，将完整独立1H目录放入清单指定的新版本目录，添加当前8506进程的`ICT_FUTU_HOURLY_ARCHIVE`环境；保留所有现有日K、用户、实验和启动路径环境。只在该次批准范围内重启8506并重复定向／浏览器验收。不修改Windows任务、OpenD或8501。

回滚只恢复上述原8路径（新文件仅在哈希匹配时移出运行范围），移除新1H环境并恢复原启动环境；保留新数据和证据。**绝不把旧用户库或实验库备份覆盖回当前用户资料**，不回退既有日K归档或其版本指针。发布前还需针对届时当前生产状态重新检查及演练；本轮没有执行正式部署或正式回滚。

## 执行命令与输出

以下为关键命令。工作树创建在原仓库执行，其余在独立工作树的`ict_trade_assistant`目录；采集与测试Python为`C:/Users/cbcbe/TradingCodex/ict_trade_assistant/.venv/Scripts/python.exe`，最初预检使用全局Python：

```text
git fetch origin
git worktree add .worktrees/v046-history-workbench -b codex/ict-v046-history-workbench 15fc7ed
python .local/preflight.py --opend
python scripts/capture_futu_hourly.py --output .local/v046/hourly_20261109_v1
python scripts/verify_futu_hourly.py --capture .local/v046/hourly_20261109_v1 --output .local/v046/hourly_20261109_verified
python .local/probes.py
python scripts/verify_v046_evidence.py --archive .local/v046/hourly_20261109_verified --daily .local/v046/daily-baseline.sqlite3 --probes .local/v046/boundary-probes --output .local/v046/data-evidence-final.json
python -m pytest tests/test_v046.py tests/test_v0441.py tests/test_experiment_v044.py tests/test_futu_daily.py tests/test_futu_update_v045.py tests/test_futu_task_lifecycle.py tests/test_core.py tests/test_plans_levels.py tests/test_observations.py tests/test_ict_v03.py tests/test_v04_live_gate.py tests/test_decision_v04.py tests/test_v04_review_fixes.py tests/test_deployment_protection.py -q --junitxml=.local/v046/final-regression.xml
python -m pytest tests/test_v046.py tests/test_futu_daily.py tests/test_v0441.py tests/test_experiment_v044.py -q --junitxml=.local/v046/price-scale-final.xml
python -m pytest tests/test_v046.py -q --junitxml=.local/v046/v046-final.xml
python -m compileall -q desk scripts tests/test_v046.py
npx --offline --yes --package @playwright/cli playwright-cli -s=ict-v046 open http://127.0.0.1:8526 --browser chrome
npx --offline --yes --package @playwright/cli playwright-cli -s=ict-v046 run-code --filename scripts/v046_browser_check.js
npx --offline --yes --package @playwright/cli playwright-cli -s=ict-v046 run-code --filename scripts/v046_card_check.js
python .local/protect_final.py
& .local/task_hashes.ps1
git diff --check
```

另在核对心跳、父子关系和端口参数后重启过**本任务8526**以载入修改；其余服务不操作。浏览器连接器配置被占用后改用现有离线Playwright CLI；验收脚本已修正SPY/SPYM精确选项及异步旧图等待，失败尝试没有算作通过。Windows AppTest的本地套接字需沙箱外执行；没有安装新依赖。

本目录提供可审查的最终摘要及证据；原始资料、逐页记录、完整数据库快照和开发日志保留在本地`.local/v046`，不提交用户数据库或秘密信息。当前成果为历史资料与UI工程验收，不能作为实盘资格、交易优势或策略收益证明。正式8506仍为原v0.4.5，等待单独部署批准。
