# v0.4 离线验收

## 最终上线安全门禁（2026-11-01）

修复前先复现“合成完整CE链＋新鲜报价”获得live_review及执行审查动作，两项测试均失败（含报告声称资格已通过的输入），日志 `data/v04_live_gate/before.txt`。

新增独立ICT资格模块，v0.4发布授权固定关闭、无运行时开关。报价合格仅影响基础行情资格；历史CE仍是历史人工观察。未来实时证据接口契约的正向测试不授予实时资格；缺实际到达、到达超前、RTH未通过、版本不符、资格过期、历史来源或确认不足均拒绝。11项定向测试通过，日志 `data/v04_live_gate/targeted.txt`；全量132项回归通过（139.72秒），见 `full-pytest.txt`。合成契约不能证明实际市场实时资格。

本轮不改识别器、排序、90秒门禁、策略参数、用户数据库或v0.3；原用户表和源码只读复核见 `data/v04_live_gate/prefix.txt`。真实RTH与独立ICT实时确认、数据实际到达证据仍全部PENDING。PR保持DRAFT、不合并、不部署。本轮结束冻结v0.4，不再扩大开发范围。

冻结审计：三个排序／结构选择函数源码逐一对比未变，行情资格、识别器及数据库文件无代码差异，见 `safety-invariants.json`；56个历史前缀时点及原五表指纹复核一致。以本轮最终Git提交为v0.4冻结点，指纹清单保留在本机 `data/v04_live_gate/frozen-manifest.json`。没有创建后续开发任务或自动解锁任务。

## PR #39 定向修复复验（2026-11-01）

修复前提交f73a386：先新增六项复现测试，六项全部失败。三项分别复现已失效链、已过期链和失效独立FVG被加入当前区域；两项分别复现证券内部及跨证券的独立FVG抢占合格Sweep；一项实际Streamlit页面复现OUTSIDE显示“接近关键价”。原始失败记录：`data/v04_review/before.txt`。

最小修复只涉及决策层区域过滤、共用结构优先级和候选／卡片文案；不改识别器、行情资格、90秒门禁、参数或原始事件。失效证据与原因保留，next_region为空，价格观察与失效结构独立。六项原失败测试修复后全部通过，另增加INSIDE/NEAR页面文案回归。全量121项通过（原113项＋本轮8项），用时141.20秒；完整结果见 `data/v04_review/full-pytest.txt`。

四证券56个真实历史前缀时点再次一致，原用户五表及源码指纹未变，SQLite完整性ok。2560×1440和1440×2560分别点击四证券，候选与SOP卡同步，卡片下一观察区域的完整精度边界与图表关注线一致；历史图层保留、0页面异常、无溢出、ICT提醒锁定关闭，证据 `data/v04_review/browser.txt`、`prefix.txt`，截图 `output/playwright/v04-review-2560.png` 与 `v04-review-1440.png`。失效／过期及关联完整链情形由明确标记的合成测试覆盖，不宣称真实市场通过。

8506仅本轮历史快照验收使用，测试后停止；8501原PID 44052不重启、不修改。数据库路径仍隔离，未迁移或覆盖原SQLite。PR #39保持DRAFT，不合并、不部署；真实RTH全部保留PENDING。以下为先前v0.4交付记录。

日期：2026-11-01。工程实现与离线验证不代表真实市场通过；真实RTH仍为 `PENDING_LIVE_ACCEPTANCE`。完整链测试采用明确标记的合成数据，真实完整MSS链仍为零。

## 输入与冻结

基线提交 `92ce0a2f8c371dbea742ac2c5c92228be72d53e0`；v0.3基线95项测试通过。既有真实历史快照SHA256：`4e9296cbcd37b605db5e5ae98661477e87cc81dd580cb15072daba982c4ed5cc`。样本不新增：7条Sweep、27个独立FVG。v0.3识别器、参数与RTH清单未修改；原未跟踪文件保留。

原库通过只读连接备份并逐表比较 `notes/plan_versions/settings/events/acknowledgements`，本轮指纹一致，完整性为ok。证据：独立工作树 `data/v04_acceptance/baseline.json`、`offline-evidence.json`、`v03-user-backup.sqlite3`。备份含用户数据，仅留本机，不提交Git。

新工作树的Git检出换行为CRLF，原工作目录为LF；原文件字节SHA256照常冻结，新旧识别器以统一换行后的源码内容比较，Git无识别器差异。没有修改原文件来迁就验收。

## P5检查映射

|项目|验证与边界|
|---|---|
|四证券去重与区域聚合|排列所有输入顺序，最多四证券；闭区间区域合并且不修改原记录|
|确定性及稳定排序|数据资格优先、固定阶段、距离／共振／时效／证券tie-break|
|事件推进、失效与过期|合成Sweep→MSS→FVG→CE；失效及日历期限；不放宽冻结规则|
|真实历史因果|四证券×14个时点，完整输入与当时前缀比较结构及价格观察决策|
|1H收盘加2分钟|冻结识别器门禁及决策层证据known_at复核|
|形成中、缺分钟、异常行情|冻结测试及新增阻断测试；4H输入UNKNOWN|
|独立FVG与完整链|独立FVG linked=False，禁止推进CE复核；完整链仅合成测试|
|图表坐标与决策证据|相同报告输入；逐事件确认时间与价格匹配图层坐标|
|多窗口输入|浏览器双窗口自动刷新，独立未提交备注；计划版本冲突拒绝旧窗口覆盖|
|原数据及事件保留|原目录源码、未跟踪文件及五表指纹一致；新库完全隔离|
|独立有界稳定性|见下述专门证据；不外推数小时或真实盘中|
|账户订单不可达|全生产Python AST扫描禁用账户／订单符号；Provider仍只使用OpenQuoteContext；浏览器入口替换行情为历史快照|

## 命令及自动测试

使用原项目虚拟环境Python，在独立v0.4工作树执行：

```text
python -m pytest -q -p no:cacheprovider
python -m pip check
python scripts/v04_offline_acceptance.py --original C:/Users/cbcbe/TradingCodex/ict_trade_assistant
git diff --check
npx --yes --package @playwright/cli playwright-cli -s=ictv04 run-code --filename scripts/v04_browser_setup.js
npx --yes --package @playwright/cli playwright-cli -s=ictv04 run-code --filename scripts/v04_browser_soak.js
```

全量113项测试通过（原95项＋新增18项），pip check与diff检查通过。依赖弃用警告保留，未通过修改依赖或降低断言消除。最终图表标签仅改为可读区域名，浏览器布局重新验证。原始记录在 `data/v04_acceptance/pytest.txt`、`history-run.txt`、`layout.txt`。截图在 `output/playwright/v04-landscape.png` 与 `v04-portrait.png`。

## 稳定性中断记录

首次Python子进程轮询只有三个有效双窗口采样；宿主时钟跳变约六小时后返回负数超时，浏览器会话不可用。该次失败保留在 `browser-soak-interrupted.jsonl` 与 `soak-interrupted-summary.json`，不能称作六小时或180秒稳定性通过。pytest显示的约六小时耗时同样受此跳变影响，只报告测试结果，不将其视作连续运行证据。

随后改用单个浏览器会话内每10秒采样，超过30秒采样间隔立即失败，不自动重启服务，也不改ICT条件。最终连续180.204秒、19次采样通过：双窗口备注均保留、0页面异常、面板齐全、ICT提醒始终关闭、19次健康检查为ok。时间为香港2026-11-01 17:35:36至17:38:36。结果记录 `data/v04_acceptance/browser-soak.txt`。这不是盘中验收，也不外推到采样间隙或数小时运行。

最终将实际完整决策快照写入计划版本后逐字段比较其JSON持久化表示（区域元组持久化为数组），20项相关回归通过，见 `final-targeted-tests.txt`。

发布目录全量113项通过。最终审查补充独立FVG期限结束的失效原因测试，先复现空提示，再补齐文字回退；不改条件及排序。失败证据保留 `expiry-regression-before.txt`，修复后在实际发布目录回归相关20项。

## 待真实RTH

新报价推进、90秒门禁真实触发、候选距离实时变化、自然价格状态转换及提醒去重、双窗口盘中稳定、断线恢复与安全阻断全部PENDING。保留 `LIVE_RTH_ACCEPTANCE_CHECKLIST.md` 原门禁；星期一仍使用v0.3，不用v0.4替代正式验收。Windows物理双屏及系统缩放不由浏览器CSS视口通过证明。
