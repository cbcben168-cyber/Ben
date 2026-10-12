# C1 Phase 3 批量 Edge 研究报告

## 执行结论

- 实际注册并计算：36个价格类候选因子；数据不合格候选未纳入。
- 数据资格：`PASS_5M_ONLY`，19,470根缓存全部命中；没有使用1分钟、Volume、VWAP或账户数据。
- V3.1.1一致性：`PASS`。若不是 PASS，本报告的策略排名和晋级结论一律 fail-closed。
- 高重合因子对：1组（|phi|≥0.80），已标记而不是重复计为独立假设。
- 满足 TRAIN_CANDIDATE：0个；TRAIN 结果不能升级为已验证 Edge。

## 策略及过滤后独立重演

- S01_BASE：808笔，净期望 -4.00bp，PF 0.48，状态 `NO_EVIDENCE`。
- S01_F015：9笔，净期望 -1.14bp，PF 0.91，状态 `NO_EVIDENCE`。
- S01_F036：598笔，净期望 -4.15bp，PF 0.48，状态 `NO_EVIDENCE`。
- S02_BASE：183笔，净期望 -0.65bp，PF 0.93，状态 `NO_EVIDENCE`。
- S02_F023：24笔，净期望 +3.55bp，PF 1.43，状态 `NO_EVIDENCE`。
- S02_F029：19笔，净期望 +5.56bp，PF 1.84，状态 `NO_EVIDENCE`。
- S03_BASE：81笔，净期望 -4.04bp，PF 0.56，状态 `NO_EVIDENCE`。
- S03_F021：9笔，净期望 -7.73bp，PF 0.19，状态 `NO_EVIDENCE`。
- S03_F034：58笔，净期望 -4.48bp，PF 0.55，状态 `NO_EVIDENCE`。

过滤版本均从原始信号队列重新运行独立持仓状态，过滤导致的仓位释放会让后续原 `POSITION_BUSY` 机会重新参与；没有采用“删除已有亏损交易并置零”的固定机会集方法。

## 市场环境与时间现象

- S02_BASE / premarket_trend=BULL：64笔，净期望 +2.01bp（探索性，同一TRAIN样本）。
- S02_BASE / time_bucket=10:30-12:00：71笔，净期望 +1.81bp（探索性，同一TRAIN样本）。
- S02_BASE / premarket_vol=LOW：57笔，净期望 +1.21bp（探索性，同一TRAIN样本）。
- S02_BASE / premarket_vol=NORMAL：57笔，净期望 +1.18bp（探索性，同一TRAIN样本）。
- S02_BASE / dynamic_gap=GAP_UP：51笔，净期望 +0.31bp（探索性，同一TRAIN样本）。

这些仅是预注册单一维度诊断，不是独立验证；不得据此继续无约束调参。

## 性能与复现

- 数据准备：0.088秒；缓存命中 `true`。
- 因子、策略与统计：9.852秒。
- 完整批量执行：9.940秒。
- 人工操作：运行一次 `python run_research.py`；无需富途GUI、账户或订单操作。
- 自动重复运行：具备。相同输入、注册表与随机种子生成相同核心研究结果；运行耗时字段允许变化。

## 增加10个因子

只需在源 `FACTOR_REGISTRY.csv` 增加10条冻结定义，并在 `compute_factor_matrix()` 增加对应10个确定性公式及单元测试。数据 Gate、Regime、统计、报告、相关性和策略重演框架无需改动；人工步骤仍为一次命令。

## 当前限制与下一步最小工作

1. 当前 TRAIN 已多次被研究，所有 Phase 3 结果均为探索性，不能替代独立 Validation/OOS。
2. 没有合格1分钟路径；同柱止盈止损只能保守处理并披露敏感性。
3. 必须先解决任何 `BLOCKED_STATE_MACHINE_MISMATCH`，否则不得采用策略结论。
4. 只有用户另行批准后，才能冻结极少数 TRAIN_CANDIDATE 并进入独立 Validation；若候选为零，保持冻结不推进。
