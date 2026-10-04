# ES/MES 研究操作说明

## 如何选择用不用

项目：C:\Users\cbcbe\Documents\Codex\2026-10-03\referenced-chatgpt-conversation-this-is-an\work\es-mes-integration\es_mes_research。

运行scripts/choose.ps1，0关闭、1 ES、2 MES、3两者。默认0，状态没有选择文件时也关闭。修改选择不自动运行采集/回测；关闭不删除历史结果。单独运行的研究任务开始前检查选择，运行过程中不热切换；本项目没有常驻、调度、下单或账户接口。

使用现有已验证Python运行库，不改变全局配置/依赖，也不安装到SPY虚拟环境。命令的PYTHONPATH只指向本项目src；菜单退出会恢复环境。若需要独立虚拟环境，可按pyproject.toml另行安装，本轮未安装。

```powershell
# 在项目目录；可以把这一块放在单独的PowerShell会话中
$env:PYTHONPATH='src'
$researchPython='C:\Users\cbcbe\Documents\ChatGPT\Futu\spy_intraday_research\.venv\Scripts\python.exe'
& $researchPython -m es_mes.cli status
& $researchPython -m es_mes.cli select --choice none
& $researchPython -m es_mes.cli select --choice ES
& $researchPython -m es_mes.cli select --choice MES
& $researchPython -m es_mes.cli select --choice both
& $researchPython -W once::DeprecationWarning -m es_mes.cli probe
```

probe可在关闭状态检查数据权限，只访问quote context。目录返回并不代表有CME报价/历史权限。权限不足立即停止该请求，不无效重试、不展示原始券商错误或账户信息；临时失败最多3次。官方权限：[Futu权限与额度](https://openapi.futunn.com/futu-api-doc/intro/authority.html)。

## 真实数据入口

不自动购买数据、不用免费日线拼接分钟，不把SPY价格改名成ES/MES，不把ES行情乘10当MES成交。两个市场分别需自己的实际合约1m数据。

支持UTC起始时刻CSV导入与明确实际合约Futu分页采集。导入列：ts_start_utc（必须Z或时区偏移）、contract、open、high、low、close、volume。所有价格必须合法0.25 tick，OHLC有限正数、volume非负、每合约分钟唯一。

换月CSV列：session_date（ISO）、contract、expires_on（该实际合约最后交易日）、known_at_utc（映射何时已知）。每现金交易日一行、完整覆盖指定范围；实际合约代码如US.ES2612/US.MES2612或原生ESZ6/MESZ6。main/current/next、跨期价差、后复权主连不允许作为可执行价格。

映射不得晚于当天开盘；换合约必须在上一个现金收盘前已知，不能用当天最终成交量决定当天交易。最后交易日及以后拒绝交易，防止早于现金开盘到期。合约到期日期必须一致，来源真实性/时区含义仍需外部资格验证，不能靠用户声明自动晋级。

每个日期只取09:30至XNYS当日收盘，390/210分钟严格完整；现金休市日期不研究，即便期货开放。不填缺失价格，不跨合约混成一个bar，不忽略DST。全量数据保留在自己的目录，计算Train前再次过滤，独立样本不计算收益。

```powershell
# 下列是操作模板，路径和日期替换为你的真实数据；不是已有数据
& $researchPython -m es_mes.cli import-data --product ES --input YOUR_REAL_MINUTES.csv --roll-map YOUR_REAL_ROLL_MAP.csv --start 2023-01-03 --end 2026-10-02
# 单合约采集：timezone/semantics/expiry必须按供应商实际定义填写，不自动猜测
& $researchPython -m es_mes.cli collect --product ES --contract US.ES2612 --start 2026-09-21 --end 2026-10-02 --expires-on 2026-12-18 --timezone America/New_York --semantics end
```

采集模板中的时区、结束时间戳和到期日期仅示例声明，尚未通过实际ES/MES历史数据核实；必须先确认，错误时区会使窗口缺失并拒绝。Futu的[期货合约资料](https://openapi.futunn.com/futu-api-doc/en/quote/get-future-info.html)包含时区元数据，可作为后续资格证据。单一实际合约采集不会自动换月；跨多年回测使用真实多合约数据和明确换月CSV。

## 成本与策略

官方参数：ES每点50美元、MES每点5美元；tick均0.25点，分别12.50/1.25美元。[CME规格](https://www.cmegroup.com/articles/faqs/frequently-asked-questions-micro-e-mini-equity-index-futures.html)。不使用SPY的2bps作为期货手续费。

费用默认未设置，回测拒绝缺费用。明确设置每合约往返全部费用（佣金+交易所+其他）和每市场单方向执行的滑点tick；ASSUMED不等于实测。VERIFIED标签由用户声明，仍非独立验证。以下金额仅展示CLI写法，必须换成你的实测或明确假设，项目默认没有这些数值。

```powershell
& $researchPython -m es_mes.cli costs --product ES --round-trip-fee-usd 5 --slippage-ticks 1 --cost-basis ASSUMED
& $researchPython -m es_mes.cli costs --product MES --round-trip-fee-usd 2 --slippage-ticks 1 --cost-basis ASSUMED
& $researchPython -W once::DeprecationWarning -m es_mes.cli backtest --product ES
& $researchPython -W once::DeprecationWarning -m es_mes.cli backtest --product MES
```

前两根5m建立OR，首次严格收盘突破、10:30排除、下根5m开盘入场；一天一笔；按确认过的原规则固定0.25宽度止损和实际入场3R。期货止损必须落在合法tick上，向风险更大方向取整：long向下、short向上。实际入场含逆向滑点，R据此计算。若原始开盘已越过止损则当日取消，不补第二笔。

入场、止损和收盘为市场成交代理，施加不利滑点；跳空止损用实际分钟开盘再扣滑点。目标作为限价：至少穿过一tick才假设填单，跳空超过目标按目标保守成交，无目标额外滑点；同时触及止盈止损仍按止损先。未出场在现金收盘退出。这些是保守模拟假设，不是实际订单填单。

只输出一合约美元PnL、净R、季度和日终美元回撤，不伪装成保证金收益率；没有资金/保证金/杠杆账户模型。持有参考在实际同合约区间首开至末收，已知换月时上个现金收盘平、次日开新合约；不把不同合约价格跳跃计为收益。持有与日内暴露不同，参考不代表同风险比较。

## 分割、结果与选择

至少500个完整现金交易日才运行首轮Train研究；60/20/20按日期分割，边界各一日embargo。少量样本可以导入作接口资格，但不输出正式回测成绩。注册先于收益计算，源码/分钟/换月SHA锁定；拒绝覆盖数据、成本锁与首次结果。失败留日志与注册，修复须新版本，不删除负结果反复重跑。

目前仅Train诊断实现，不开放Validation/OOS命令。还未实现matched controls、bootstrap、费用压力和独立资格，formal_data_gate=false，不输出KEEP。ES/MES同一指数高度相关，不能当两次独立验证。夜间/CME全时段、实时forward/每日收盘调度均未实现；当前CSV/MD是研究完成后的汇总与等待选择记录，不能宣称已在每天跑。

data/ES、data/MES各自独立缓存/manifest/roll_map；state为选择与费用；artifacts为权限probe、各自Train CSV/MD/JSON及optimization_choices.csv；logs受控错误。全部行情、状态、日志不提交GitHub；敏感配置只环境变量名称，绝不写密码/密钥/账户。

A保持研究规则；B先解决数据/成本资格；C登记单一新增假设。用户选择后才能另行优化，当前版本不自动变。
