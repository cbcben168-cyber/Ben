# C1 Phase 3.2 Statistical Integrity Repair Handoff

更新时间：2026-10-12（Asia/Shanghai）

## 当前状态

- 工作树：`C:\Users\cbcbe\.codex\worktrees\futu-factor-progress-dashboard-v1\Futu`
- 分支：`codex/futu-factor-progress-dashboard-v1`
- 基准 HEAD：`dcd4ad37609b46b405c6732c1a55918f3f0f91fd`
- Draft PR：#33；本阶段未提交、未推送、未修改 PR、未合并。
- Phase 3.2 已完成并通过本地验收；Phase 4 未启动。
- 冻结 V1/V2、V3.1.1 原始 RunLog、因子/策略注册表、策略与模拟器、Dashboard SQLite/`data/` 均未修改。

## 修复内容

- `factor_results()` 现在同时输出 `baseline_raw_market`、`baseline_directional` 与 `baseline_mean`。
- Long：`baseline_directional = baseline_raw_market`；Short：`baseline_directional = -baseline_raw_market`；`increment = directional_mean - baseline_directional`。
- 推断目标冻结为 `DIRECTIONAL_MEAN_VS_ZERO`。现有 cluster CI、bootstrap、raw p-value、Holm 与 max-|t| 同时区间均针对方向调整后的均值相对 0，不解释为 increment 的显著性。
- `STATISTICS_PASS` 不再硬编码；`STATISTICS_GATE.json` 含 16 项机器可读检查、实际值、预期值和失败原因。
- 任一统计 Gate 失败会阻断候选晋级和 CLI 成功退出；受保护的 V1/V2 路径、非精确 V3 输出路径及已存在输出目录均 fail-closed。

## 正式 V3 结果

- 新冻结输出：`factor_research/phase3_edge_engine/outputs/phase3_train_v3/`
- 正式运行一次，状态：`ACCEPTANCE_PASS`。
- 子 Gate：`PASS_5M_ONLY`、`ENGINE_PASS`、`STATISTICS_PASS`、`TRADE_PARITY_PASS`。
- 研究结论：`RESEARCH_NO_EDGE`；TRAIN_CANDIDATE 为 0。
- 数据资格：US.SPY、TRAIN 2025-10-01 至 2026-06-30、187个交易日、14,514根5分钟K线、36个价格因子、9个完整策略版本。
- V2→V3：192条因子结果中78条Short的 `baseline_mean` 和78条 `increment` 按方向修正；其他共享因子字段无变化；27条策略结果的共享字段无变化；候选0→0。
- 九个策略的交易数、净均值与PF不变；S02_F023与S02_F029仍仅24/19笔，均为 `INSUFFICIENT_SAMPLE / NO_EVIDENCE`。
- 严格逐笔 parity 保持：1,593个信号及决策、1,072笔成交、521个 `POSITION_BUSY` 全部匹配。MFE/MAE仍不属于严格逐笔 parity 范围。
- `ENGINE_PASS != PROFITABLE_STRATEGY`；`TRADE_PARITY_PASS != REAL_EXECUTION_PASS`；`TRAIN_CANDIDATE != VALIDATED_EDGE`。

## 完整性证据

- 输入 SHA256：OHLC `e5e3ab7cfa981be022388b7a54952a6f8fa29e2dc0043672edf4e84997940e2f`。
- OHLC audit manifest：`f1f750867dd4a32eaf74d4d776dcf47002f0aa7f5b123db4177e57c4a1a266da`。
- `opend_rehab.csv`：`16a1bae16d562edffac364cbba2a6a26d72765e1eca57ab0c31189b37ceb17c4`。
- V3.1.1 RunLog：`6523875e998a79f17a1047937f70dbe2b383486caa50d53d91e70a1183acd840`。
- 正式运行前后复核：V1共16个、V2共20个声明冻结文件均0个哈希不匹配；V3 manifest声明的22个产物均0个哈希/大小不匹配。
- 未访问 Validation/OOS、账户、资金、持仓、订单或交易接口；未启用 Volume、RVOL、VWAP或1分钟数据。

## 验证记录

- Phase 3专项：`39 passed in 53.01s`。
- 全仓：`289 passed in 105.80s`。
- 负向注入覆盖：Short基准符号错误、increment错误、注册家族缺行、非法p值、无效同时区间；均能使统计 Gate 失败。
- `git diff --check` 通过（仅Git提示未来LF/CRLF转换）。

## 后续边界

- 不得覆盖或重跑到现有 `phase3_train_v3/`；该目录视为冻结证据。
- 不得访问 Validation/OOS，不得修改既有候选标准，不得为获得正收益而调参。
- Phase 4 的最低准入条件：用户先审核本交接和V3证据，并明确批准新的写入范围、冻结研究规则与新版本输出目录。
- 可直接复用：数据资格、因子计算、独立状态机重演、逐笔parity、交易日聚类bootstrap、多重检验与机器可读Gate框架。
