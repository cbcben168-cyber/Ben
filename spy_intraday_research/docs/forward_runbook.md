# SPY 诊断 Forward Test 运行说明

日期：2026-10-03。当前可运行版本：`diagnostic_v2`。

## 当前能做什么

实时读取Futu已完成分钟线与报价，按冻结的四类setup（ORB含5/15/30m）记录信号，等待信号可用之后的新报价，再观察30分钟报价代理收益。旧报价、缺分钟、无效OHLCV、完成bar修订及超时信号会被暂停、跳过或censor。接收/处理时间和quote输入保留，可断点重启并去重。

**这是未验证优势的诊断shadow，不是券商paper成交。** 可执行成交始终为0，程序没有交易账户或订单接口。last-price代理不能等同于可成交bid/ask；2bps是额外保守成本假设。重叠观察不是资金组合回测，不计算误导性的年化Sharpe。

收盘自动生成CSV、中文MD日报、MA9/20/50图和最多三个优化选项。无交易、亏损、缺数据和失败session也留记录。默认保持冻结规则；你的选择才进入新版本开发/验证，不自动改信号或TP/SL。

## 运行前条件

- Windows电脑开机、不休眠，网络正常，OpenD已登录；Python环境仅在项目`.venv`。
- 行情API能够订阅US.SPY 1m和QUOTE；开盘时必须实际检查quote时间是否新鲜。周末接口成功只能证明可连接，不能证明实时资格通过。
- `data/normalized`有已核验历史与至少60日预热；`locks/baseline_v1/state_model.json`与`locks/diagnostic_v2/lock_manifest.json`已生成。
- 新代码与锁内科学/运行时hash一致；锁、缓存和完整行情不提交公开GitHub。
- 若前一天完整数据缺失，运行程序不会用填充价格产生信号。Gap Fade企业行动接口失败时禁用该setup并记录原因。

## 启动

在 `C:\Users\cbcbe\Documents\ChatGPT\Futu\spy_intraday_research` 打开PowerShell：

```powershell
# 仅检查一次；闭市应返回CLOSED，不做报价交易观察
.venv\Scripts\python.exe -m spy_research.cli paper --once --version diagnostic_v2

# 持续运行，闭市等待，实际交易日开盘后采集，收盘复盘
.venv\Scripts\python.exe -m spy_research.cli paper --version diagnostic_v2

# 或使用项目启动脚本
.\scripts\start_shadow.ps1
```

建议开盘前15分钟启动进程。运行中按Ctrl+C结束；checkpoint保留，当前未完成观察不伪装成完成收益。当前没有安装Windows自动启动任务，也没有后台常驻进程；关闭终端会停止运行。启动脚本不改变系统执行策略或自动安装依赖。

纽约日历自动处理DST、节假日和半日市。下一个常规交易日为2026-10-05，09:30 ET对应北京时间21:30；未来冬令时会变为22:30，不要硬编码北京时间。

## 输出与每日选择

`artifacts/paper/diagnostic_v2/<纽约交易日>/`：

- events.csv：DETECTED/OBSERVED/SKIPPED及信号实际可用时间。
- observations.csv：QUOTE代理观察、成本、已观察MFE/MAE、COMPLETE/CENSORED；不是订单成交。
- quotes.jsonl / quotes.csv：接收时间、交易quote时间、价格和新鲜度。
- operational.csv / session_summary.json：异常、RTH分钟完整性及运行状态。
- review_001/daily_review.md：当日与累计结果、归因、限制和优化选项。
- daily_metrics.csv、cumulative_metrics.csv、optimization_options.csv、optimization_decisions.csv与review_manifest.json。
- entry_exit_ma.png：SPY 1m与MA9/20/50，明确无broker fills。

你可以回复“选A/B/C”并引用日期/Proposal ID。选择只记录方向；现有冻结版本保持不变。新候选必须预登记未来窗口并重新验证，不能拿已经看过的历史当独立OOS。

手动补出日报：

```powershell
.venv\Scripts\python.exe -m spy_research.cli daily-review --version diagnostic_v2 --date YYYY-MM-DD
```

异常退出留下runner.lock时不要并发再启。确认原进程已经结束，再检查checkpoint和日志；这是本地观察锁，不能用删除锁代替任何券商持仓对账。本项目不连接券商持仓。

## 历史研究命令与门槛

```powershell
.venv\Scripts\python.exe -m spy_research.cli collect --start 2023-07-03 --end 2026-10-02
.venv\Scripts\python.exe -m spy_research.cli prepare --start 2023-07-03 --end 2026-10-02
.venv\Scripts\python.exe -m spy_research.cli register --start 2023-10-02 --end 2026-10-02
.venv\Scripts\python.exe -m spy_research.cli study --split train
# 有合格候选才可执行；当前将拒绝，不消耗holdout：
.venv\Scripts\python.exe -m spy_research.cli evaluate --split validation
.venv\Scripts\python.exe -m spy_research.cli lock
.venv\Scripts\python.exe -m spy_research.cli evaluate --split locked_oos
```

Train状态阈值、matched controls、10,000次交易日/5日block bootstrap、Holm校正、成本/延迟/去top5/季度/邻域检查已实现。没有KEEP候选，不调TP/SL、不打开Validation/OOS、不转broker paper。Buy and Hold资金基准与可投资组合验证属于后续合格执行模型；事件研究的普通时点对照已经提供，两者不能互相代替。

当前全部12个组合为WEAK：数据资格未通过、样本不足或推断/稳定性不足。成交量差异未解释，未来诊断观察不能替代它的资格认证。要声称验证后的策略paper ready，仍须正式数据gate、Validation、Locked OOS及执行模型通过。

## 软件测试与真实市场测试的区别

历史重放用 `replay_*` 独立目录，quote来自合成的历史close代理，日报醒目标为replay，绝不计入未来累计样本。软件测试通过只证明代码行为；今天是周末，首个真实开盘session的新鲜度、延迟与数据修订仍需现场验证。不会提前宣布完成60天/100笔的forward验收。
