# C1 Phase 3 Handoff

更新时间：2026-10-12（Asia/Shanghai）

## 当前状态

- 工作树：`C:\Users\cbcbe\.codex\worktrees\futu-factor-progress-dashboard-v1\Futu`
- 分支：`codex/futu-factor-progress-dashboard-v1`
- Draft PR：#33；保持 Draft，不合并。
- Phase 3.1 独立统计与重演审计修复已实现，入口为 `python run_research.py`。
- 冻结 V3.1.1 策略、原始 RunLog、Dashboard SQLite/`data/`、历史 Gate 均未修改。

## 数据与边界

- 输入为已审计 `opend_5m_ohlc.csv`：19,470根、251个RTH交易日；TRAIN为2025-10-01至2026-06-30，共187日。
- 数据 SHA256：`e5e3ab7cfa981be022388b7a54952a6f8fa29e2dc0043672edf4e84997940e2f`。
- 处理3个半日市和4次动态前复权；缓存命中，不重新下载全年数据。
- 没有合格1分钟缓存；只允许5分钟级研究。Volume、RVOL、VWAP、账户、持仓、订单、Validation/OOS全部禁用。

## 实现与验收

- 源模块：`factor_research/phase3_edge_engine/`；冻结注册36个因子和9个策略版本。
- 原始输出 `phase3_train_v1/` 保持冻结；新输出为 `factor_research/phase3_edge_engine/outputs/phase3_train_v2/`。
- `ENGINE_PASS`、`STATISTICS_PASS`、`TRADE_PARITY_PASS`；研究结论为 `RESEARCH_NO_EDGE`。
- V3.1.1严格逐笔一致性：1,593/1,593个信号及决策、1,072/1,072笔交易、521/521个拒绝逐项匹配。价格转换为最终前复权基准后最大差不超过`5.01e-10`，净收益最大差不超过`5.21e-15`。
- S01/S02/S03分别重演808/183/81笔；净期望约-4.00/-0.65/-4.04bp，交易数与点估计相对V1不变。
- 统计目标明确为每笔交易/事件期望；整日聚类重抽样后重新计算同一估计量；同一检验族使用共同交易日索引，Holm保持完整预注册家族规模。
- `opend_rehab.csv` 的SHA256、schema、四行身份及全部复权系数均 fail-closed 校验，并写入结果manifest。
- 过滤器使用独立持仓重演；S01_F036重新接纳57个原基准POSITION_BUSY机会。
- 结果为0个TRAIN_CANDIDATE。S02_F029和S02_F023虽有正向描述值，但仅19/24笔，未过样本和同时区间门槛。
- 高重合因子对1组：F001/F002；没有当作独立发现重复计数。
- Phase 3专项测试：21 passed（55.33秒）；最终全仓测试：271 passed（115.77秒）。

## 后续边界

- 所有新结果标记为同一TRAIN样本上的探索结果，不是独立Edge。
- 不得访问Validation/OOS，不得调参追逐盈利，不得连接账户或下单。
- 若用户批准新一轮研究，先冻结新增注册表版本；新增10个因子只需增加10条注册和10个公式/测试，其他框架不变。
