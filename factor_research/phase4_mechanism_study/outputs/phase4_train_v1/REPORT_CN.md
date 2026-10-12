# C1 Phase 4.3 One-Shot TRAIN 研究报告

## A. 数据与执行

- 数据：US.SPY 5分钟RTH，2025-10-01至2026-06-30，187个交易日、14514根K线。
- OHLC SHA256：`e5e3ab7cfa981be022388b7a54952a6f8fa29e2dc0043672edf4e84997940e2f`；动态前复权；America/New_York bar-end。
- 仅完整源文件用于身份核验；数值解析与特征、交易、收益计算均限制在TRAIN价格范围内。
- 三机制按冻结状态机共同执行；下一根同日K线开盘成交；取消信号不计收益；STOP_FIRST为主口径。
- 未读取Volume、RVOL、VWAP、1分钟、Validation/OOS、账户、持仓或订单数据。
- Buy and Hold描述性基准（首根开盘至末根收盘，扣4bp）：+1256.6119 bp。
- 最大回撤口径：按信号时间顺序累加每笔4bp后净收益，计算累计曲线相对历史峰值的最大回撤幅度；不是资金权重组合回撤。

## B. 三项策略结果

### P4_M01_ALL

- 交易/独立交易日：157/157；Long/Short：77/80。
- 4bp后均值：-4.8938 bp；PF：0.383499；胜率：0.363057。
- 平均盈利/亏损：+8.3850 bp / -12.4627 bp；最大回撤：+795.6093 bp。
- 2/4/6bp均值：-2.8938 bp / -4.8938 bp / -6.8938 bp。
- Holm p值：0.001499；95%同时区间：[-7.3319 bp, -2.4557 bp]。
- 正收益月份：1；最大单月正利润占比：1.000000。
- Long/Short 4bp均值：-4.2514 bp / -5.5121 bp。
- 信号取消：20/177；同柱双触发：0；TARGET_FIRST均值：-4.8938 bp。
- 样本资格：CAPACITY_OK/QUALIFIED；最终状态：`RESEARCH_NO_EDGE`。

### P4_M02_ALL

- 交易/独立交易日：35/35；Long/Short：10/25。
- 4bp后均值：+1.3314 bp；PF：1.184324；胜率：0.428571。
- 平均盈利/亏损：+19.9600 bp / -12.6401 bp；最大回撤：+150.0126 bp。
- 2/4/6bp均值：+3.3314 bp / +1.3314 bp / -0.6686 bp。
- Holm p值：1.000000；95%同时区间：[-6.7787 bp, +9.4414 bp]。
- 正收益月份：6；最大单月正利润占比：0.324128。
- Long/Short 4bp均值：-1.8018 bp / +2.5846 bp。
- 信号取消：0/35；同柱双触发：0；TARGET_FIRST均值：+1.3314 bp。
- 样本资格：BELOW_MINIMUM_CAPACITY/BELOW_MINIMUM_CAPACITY；最终状态：`NO_EVIDENCE_BELOW_MINIMUM_CAPACITY`。

### P4_M06_ALL

- 交易/独立交易日：18/18；Long/Short：10/8。
- 4bp后均值：-0.0893 bp；PF：0.994078；胜率：0.444444。
- 平均盈利/亏损：+33.7329 bp / -27.1471 bp；最大回撤：+104.6440 bp。
- 2/4/6bp均值：+1.9107 bp / -0.0893 bp / -2.0893 bp。
- Holm p值：1.000000；95%同时区间：[-22.2598 bp, +22.0812 bp]。
- 正收益月份：3；最大单月正利润占比：0.623055。
- Long/Short 4bp均值：+5.1236 bp / -6.6055 bp。
- 信号取消：0/18；同柱双触发：0；TARGET_FIRST均值：-0.0893 bp。
- 样本资格：BELOW_MINIMUM_CAPACITY/BELOW_MINIMUM_CAPACITY；最终状态：`NO_EVIDENCE_BELOW_MINIMUM_CAPACITY`。

## C. 风险解释

- P4_M01_ALL：4bp后平均收益不足以覆盖成本；6bp稳健性均值不大于零；正利润受少数月份主导。这些诊断不生成新过滤版本。
- P4_M02_ALL：Phase 4.2已冻结为容量不足，因此收益外观不能支持晋级；6bp稳健性均值不大于零。这些诊断不生成新过滤版本。
- P4_M06_ALL：Phase 4.2已冻结为容量不足，因此收益外观不能支持晋级；4bp后平均收益不足以覆盖成本；6bp稳健性均值不大于零；正利润受少数月份主导。这些诊断不生成新过滤版本。

## D. 研究结论

- DATA_GATE：`PASS`
- PREREGISTRATION_GATE：`PASS`
- ENGINE_GATE：`PASS`
- STATISTICS_GATE：`PASS`
- MULTIPLE_TESTING_GATE：`PASS`
- REPRODUCIBILITY_GATE：`PASS`
- RESEARCH_STATUS：`RESEARCH_NO_EDGE`

工程Gate通过不等于交易优势得到验证。本报告只评价当前冻结TRAIN中的探索性假设，不构成Validation、OOS、Forward或实盘结论。
