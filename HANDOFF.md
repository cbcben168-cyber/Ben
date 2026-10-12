# C1 Phase 3 Handoff

更新时间：2026-10-12（Asia/Shanghai）

## 当前状态

- 工作树：`C:\Users\cbcbe\.codex\worktrees\futu-factor-progress-dashboard-v1\Futu`
- 分支：`codex/futu-factor-progress-dashboard-v1`
- Draft PR：#33；保持 Draft，不合并。
- Phase 3 离线批量研究引擎已实现，入口为 `python run_research.py`。
- 冻结 V3.1.1 策略、原始 RunLog、Dashboard SQLite/`data/`、历史 Gate 均未修改。

## 数据与边界

- 输入为已审计 `opend_5m_ohlc.csv`：19,470根、251个RTH交易日；TRAIN为2025-10-01至2026-06-30，共187日。
- 数据 SHA256：`e5e3ab7cfa981be022388b7a54952a6f8fa29e2dc0043672edf4e84997940e2f`。
- 处理3个半日市和4次动态前复权；缓存命中，不重新下载全年数据。
- 没有合格1分钟缓存；只允许5分钟级研究。Volume、RVOL、VWAP、账户、持仓、订单、Validation/OOS全部禁用。

## 实现与验收

- 源模块：`factor_research/phase3_edge_engine/`；冻结注册36个因子和9个策略版本。
- 输出：`factor_research/phase3_edge_engine/outputs/phase3_train_v1/`。
- V3.1.1一致性 PASS：S01/S02/S03分别重演808/183/81笔，共1,072笔；521个POSITION_BUSY全部属于S01；净期望约-4.00/-0.65/-4.04bp。
- 过滤器使用独立持仓重演；S01_F036重新接纳57个原基准POSITION_BUSY机会。
- 结果为0个TRAIN_CANDIDATE。S02_F029和S02_F023虽有正向描述值，但仅19/24笔，未过样本和同时区间门槛。
- 高重合因子对1组：F001/F002；没有当作独立发现重复计数。
- Phase 3专项测试：13 passed；最终全仓测试：263 passed（182.91秒）。

## 后续边界

- 所有新结果标记为同一TRAIN样本上的探索结果，不是独立Edge。
- 不得访问Validation/OOS，不得调参追逐盈利，不得连接账户或下单。
- 若用户批准新一轮研究，先冻结新增注册表版本；新增10个因子只需增加10条注册和10个公式/测试，其他框架不变。
