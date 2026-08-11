# Pattern Finder Phase 1 — Milestone 3B 真实样本验证设计

## 目标

在不修改 Flat Base Detector 数学定义的前提下，把真实普通股样本从现有 8 只按 Futu 历史 K 线额度安全扩大，并提供可追溯的“像 / 勉强像 / 不像”人工验收流程。

M3B 只验证 Flat Base。Detector Version 固定为 `phase1-v1`，Detector Definition V1 的全部参数、窗口选择、支撑、阻力、pivot 和 ATR 规则保持不变。

## 已确认基线

- PR #5 已合并到 `codex/v2-2a-data-foundation-impl`，远端合并提交为 `6ef2170fc769acf260b376afbbe56c0a3709a369`。
- 干净 worktree 验证为 Pattern Finder 68 项、全量 604 项测试通过。
- 现有 Futu QFQ 缓存为 8 只，每只 380 根日线，截止 2026-08-07。
- 2026-08-10 实时额度快照：已用 8、剩余 292、明细代码 8 个。
- 现有样本 Detector 结果为 YES 2 只、NO 6 只。

## 冻结规则

生产实现不得修改 `src/tv_quant/pattern_finder/flat_base.py` 中的任何 Detector 常量或数学逻辑：

- Base Length 25–90
- Base Depth `<= 0.18`
- Bottom Tolerance `<= 0.04`
- Bottom Tests `>= 2`
- `abs(Normalized Slope) <= 0.0015`
- Detector Version `phase1-v1`
- Detector Definition V1 的 resistance、pivot low、ATR14 和窗口偏好顺序

新增测试必须直接断言上述冻结值，防止 M3B 误改 Detector。

## Universe 与安全扩样

### 候选池

维护一个约 100 只美国普通股的静态候选池。每个成员至少包含：

- symbol
- sector
- volatility bucket：低 / 中 / 高

候选池必须覆盖科技、半导体、金融、能源、医疗、消费、工业，并避免由大型科技股主导。上涨、横盘、下跌环境在缓存数据到位后，以只用于样本描述的近期价格变化进行归类；该分类不参与 Detector 判断。

### 分批目标

25 / 50 / 100 指缓存中的总样本数，包含现有 8 只。

扩样服务每次执行都：

1. 读取已有缓存，不重复下载已有且质量合格的数据。
2. 查询 Futu 当前历史 K 线额度明细。
3. 读取 `logs/futu_quota.jsonl`，执行现有每日新代码和七日滚动保护。
4. 只选择达到目标所需的缺失股票。
5. 每只下载前后重新检查并记录额度。
6. 任何额度、登录、市场权限或数据质量错误立即停止，不把部分失败包装成成功。

目标顺序为约 25、条件允许时约 50、最终约 100。若当天本地每日 25 个新代码上限不允许达到下一档，就保留已完成缓存并报告实际数量，不绕过保护规则。

## 人工验证数据

默认本地路径：

`data/processed/pattern_finder/manual_validation/flat_base_validation.jsonl`

该文件位于已忽略的本地数据目录，不提交真实人工记录。每次保存追加一行，不修改或删除旧行。同一 symbol、detector version、scan/as-of date 可以存在多次验证；页面展示最新记录，历史仍完整保留。

每条记录至少包含：

- `recorded_at_utc`
- `symbol`
- `detector_version`
- `scan_as_of_date`
- `computer_flat_base`：`YES` / `NO`
- `base_length`
- `base_depth`
- `bottom_tests`
- `normalized_slope`
- `human_label`：`像` / `勉强像` / `不像`
- `reason_tags`
- `note`

允许的原因标签固定为：底部太深、底部太短、低点不稳定、整体仍在下降、整体斜率太大、宽幅震荡、阻力不清楚、底部区间太宽、其他。

只有“勉强像”或“不像”允许保存原因标签。“像”必须保存空标签。备注去除首尾空格并限制为简短文本。任何未知标签、未知原因、Detector version 不匹配或缺失诊断字段都拒绝保存。

## Today Scan

Cache / Futu 模式扫描所有已有 M3B 缓存股票，并把最新人工结果连接到每一行。

页面展示 Computer YES / NO、四项核心诊断、Detector Version、Human Label、Reason Tags 和数据质量。筛选器提供：

- 全部
- Flat Base YES
- Flat Base NO
- 未人工验证
- 像
- 勉强像
- 不像

筛选仅改变页面显示，不改变 Detector 结果或人工历史。昂贵的缓存扫描继续使用 `st.cache_data`，轻量筛选在缓存函数之外执行。

## Chart Review

Chart Review 的真实股票选择器只列出已有本地缓存的 M3B 股票，并继续展示：

- Candlestick 和 Volume
- Detector 选中的 Base Window
- Support
- Resistance
- 全部原始 Detector diagnostics

新增一个 `st.form` 人工验证区：

- Human Label 只能选择“像 / 勉强像 / 不像”，不设置会阻止提交。
- “勉强像”或“不像”可多选原因标签。
- 可填写简短备注。
- 点击保存后才追加 JSONL，普通 Streamlit rerun 不得重复写入。
- 页面显示该股票当前 scan/as-of date 的最新人工记录和历史记录数。

## 组件边界

- `universe.py`：候选池、行业和波动率元数据；不包含 Detector 逻辑。
- 新增 `validation.py`：人工记录校验、append-only 写入、历史读取和 latest 索引。
- `cache.py`：支持显式 symbol 序列扫描，同时保留现有默认行为。
- `futu_service.py`：提供额度保护的分批扩样入口；保留现有 pilot 刷新兼容性。
- Today Scan：连接扫描行与最新人工记录并筛选。
- Chart Review：显示图表、诊断和人工验证表单。
- 独立脚本：执行 25 / 50 / 100 目标扩样并打印机器可核对的额度、缓存和失败摘要。

## 错误与阻断

- `FUTU_LOGIN_BLOCKER`：OpenD 未运行或未登录。
- `FUTU_QUOTA_BLOCKER`：剩余额度、每日新代码或七日滚动保护阻止继续。
- `FUTU_MARKET_PERMISSION_BLOCKER`：真实股票历史数据权限不足。
- `DATA_CAPABILITY_BLOCKER`：下载后数据质量未通过或历史少于 Detector 所需 120 根。
- 人工记录损坏：页面停止写入并显示明确错误，不跳过坏行伪造 latest 结果。

允许部分批次成功，但报告必须明确区分目标数量、实际数量、成功 symbol、失败 symbol 和停止原因。

## 测试策略

严格测试先行：每个生产行为先写失败测试并确认失败原因，再写最小实现。

至少覆盖：

- 100 只候选池的数量、symbol 唯一性和行业多样性。
- 分批目标只选择缺失代码并遵守额度、每日和滚动限制。
- Detector 文件未修改且冻结参数保持原值。
- JSONL 追加保存、不覆盖历史、latest 选择正确。
- Human Label 和 Reason Tags 的允许值及组合约束。
- Today Scan 七种筛选结果。
- Chart Review 表单字段、保存行为、图表覆盖层和原始 diagnostics。
- 页面和生产模块中不存在 Rounded Base、Compression、READY、Rule Score、1–5 Human Score、Shape Model、Outcome Model、ML、Future 5D/10D/20D、Optuna、Image AI、IBKR 或自动交易实现。
- Pattern Finder 测试、全量 pytest、`pip check`、`git diff --check` 和 Streamlit HTTP smoke。

## 严格范围外

M3B 不实现 Rounded Base、Compression、READY、0–100 Rule Score、正式 1–5 Human Score、Shape Model、Outcome Model、ML、未来收益标签、Optuna、Image AI、IBKR、Webhook、券商、订单或自动交易。

完成 M3B 验收报告后停止，不进入 Rounded Base。
