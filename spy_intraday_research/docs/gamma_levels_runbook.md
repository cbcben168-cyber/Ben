# Gamma 0 / Call Wall / Put Wall 独立研究

这是SPY价格信号的探索模块，不是期权下单或期权盈利回测。版本gamma_levels_v1；不修改diagnostic_v2科学源码、运行源码或冻结文件。没有历史期权链时不回填，不能把现有817天的SPY价格当成817天Gamma研究数据。

## 数据与计算

Futu完整期权链范围为采集日到之后7个自然日，快照分批最多200份，间隔3.1秒，每请求最多3次；失败留记录并停止本轮，watch后续有限重试。只用SPY标准100股合约。IV百分比转为小数，负OI、重复合约、非法IV、过期合约不合格。报价时间按ET转UTC；全部快照和SPY报价与采集结束时间之差必须0至120秒，缺时间、不完整链均不生成候选。

OI日期在Futu这些字段里未经证实，明确UNKNOWN；报价update_time也尚未被证明是可执行NBBO的新鲜度时间。即使字段时间通过也只有DIAGNOSTIC_ONLY，formal_data_gate永久false，不能晋级KEEP。

固定Call正/Put负的OI模型，不是实际做市商净持仓。BSM近似美国式SPY期权，r=q=0、到期时间采用XNYS当日16:00（半日用实际收盘）；忽略美国式提前行权、除息和利率，0DTE误差可能较大。后续需要数据/模型资格研究，不能将本近似当真实库存。模型没有按收益调整参数。

每份合约在假设价格S下重新算gamma，GEX=sign×gamma(S)×OI×100×S²×0.01，美元delta名义金额/1%变动；固定各行权价IV。搜索S的±10%范围401点，线性插值返回所有符号转换零点；无零点不外推，多个零点显示最近点并保存全部。零曲线不可识别零点。Call/Put Wall用同一模型在当前SPY价格的绝对Gamma加权OI，分别按行权价聚合最大值；并列按离现价近、再低行权价，非原始OI最大值。

0DTE、7D分别输出，7D含0DTE。0DTE当日无到期合约时不可用，不偷换成下一个交易日到期合约。

## 预登记候选规则

六条观察假设，不计为已验证策略，未来主检验须把它们及此前12项和新增尝试计入完整研究登记。2bps和30m是固定观察约定，暂无完整matched controls/bootstrap/OOS资格，不自动KEEP。

1. PUT_WALL_BOUNCE：估算net GEX正，前线收在Put Wall上，当前5m线测试该墙且收回上方，做多观察。
2. CALL_WALL_REJECT：估算net GEX正，前线收在Call Wall下，当前线测试且收回下方，做空观察。
3. CALL_WALL_BREAK_RETEST：墙下收盘→墙上收盘→下一线回踩并收墙上，做多观察。
4. PUT_WALL_BREAK_RETEST：墙上收盘→墙下收盘→下一线反抽并收墙下，做空观察。
5. GAMMA_ZERO_RECLAIM：零点下→上→回踩收上，做多观察。
6. GAMMA_ZERO_LOSS：零点上→下→反抽收下，做空观察。

只用当日首次合格快照在实际可用时刻冻结的位置；快照之前的bar不能用。只用完整连续5m线；每setup/direction/scope最多一天一次；当前数据不合格暂停。旧水平不会跨日复用。Gamma 0不是多空方向预测。

候选包含确认线极值作为失效参考和有利方向墙位目标参考；未来入场若已越过参考位应取消。入场时间不早于实际检测之后下一完整分钟，无后续观察价不填成交价。信号可能较晚发现，报告保存detected_at与signal_time，不伪装成实时下一bar成交；未实现实际成交模拟，未计算候选收益或资本曲线。现有underlying shadow仍负责自己的冻结版本日报。

## 命令

在独立项目目录，使用项目虚拟环境：

```powershell
.venv\Scripts\python.exe -m spy_research.gamma_runner collect
.venv\Scripts\python.exe -m spy_research.gamma_runner report --date 2026-10-03
.venv\Scripts\python.exe -m spy_research.gamma_runner watch --once
.venv\Scripts\python.exe -m spy_research.gamma_runner watch
```

collect可在周末运行演练，STALE/INCOMPLETE数字不能作为下一交易日入场依据。watch仅XNYS常规盘中采集和候选报告，闭市等待，Ctrl+C停止；不是系统自动启动，不部署后台任务。电脑/OpenD/网络需保持运行。与原有shadow可分别运行；Futu限流导致失败会记录，不绕过资格。

watch独占runner.lock；正常退出自动释放。进程崩溃后先确认对应PID已退出，再人工清理锁，不能在仍运行时删除。

## 每日输出

artifacts/gamma_levels_v1/YYYY-MM-DD/每次采集UTC目录：chain.csv、snapshot.csv、spot.csv、manifest.json与SHA、levels.json/csv、profile.csv、candidates.csv（仅有合格bar时）。当日目录：frozen_levels.json、daily_candidates.csv、daily_review.md、gamma_levels.png、optimization_choices.csv、failure_*.json。用户选择记录只首次创建，重复日报不会覆盖。

每轮更新当日总结，收盘后最后一次成功报告保留；没有候选也报告，无交易盈利捏造。若错过最后采集，本模块不保证拿到收盘价，报告保留真实采集时间。A保持冻结收集、B修数据资格、C数据与样本合格后单一新研究，等待用户选择，不自动优化。

失败只输出受控原因/异常类型，不输出券商响应、密码、账户、环境变量值；数据与产物均被gitignore，不发布原始行情。
