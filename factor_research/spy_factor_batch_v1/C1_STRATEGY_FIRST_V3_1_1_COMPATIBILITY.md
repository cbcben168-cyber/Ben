# C1 Strategy-First V3.1.1 富途兼容性说明

## 版本目的

`SPY_C1_STRATEGY_BATCH_TRAIN_V3_1_1.py` 是 V3.1 的平台编译兼容修复版。它不修改 F007–F012、S01–S03、市场环境、时间分层、成本、入场退出、动态复权或 114 项统计合同。

本版本只做两类兼容修复：

1. 恢复富途量化要求的 `initialize()`、`trigger_symbols()`、`custom_indicator()`、`global_variables()` 框架，并把 `declare_trig_symbol()` 限定在 `trigger_symbols()` 中。
2. 删除策略源码对平台可能覆盖的 Python `max()`、`min()`、`abs()`、`sum()`、`sorted()` 的直接调用，用普通比较、循环和策略内部辅助函数实现等价计算。

## 版本身份

- 策略文件：`SPY_C1_STRATEGY_BATCH_TRAIN_V3_1_1.py`
- `strategy_version`：`FUTU_C1_STRATEGY_BATCH_TRAIN_V3_1_1`
- `parameter_version`：`C1-STRATEGY-FIRST-TRAIN-V3.1.1`
- `contract_version`：`3.1.1`
- 日志标记：`FUTU_FACTOR_STRATEGY_V3_1_1|`
- 参数尝试次数：3
- 规范化源码 SHA256：`7b10dc0ad6e47d33372f6a473d9f3bba1884830a149504bd61c0f2ee0ff204ed`
- 冻结研究定义 SHA256：`0c73ae4ef39fda9aa472d59d2cf53cfebf7872595618319fb55bb557f4e4d562`

## 验收边界

- A. 本地富途静态兼容检查：由专用 AST 测试验证函数框架、初始化顺序、调用位置和禁用名称。
- B. 本地单元与回归测试：验证 V3.1.1 导入、114 项统计、OpenD 19,470 根 K 线回放及旧版本兼容。
- C. 富途真实代码检查：必须由用户把完整 V3.1.1 文件复制到富途编辑器后确认；本地测试不能替代该结果。
- D. 187 天正式 TRAIN：只有 C 通过后才允许开始。

V3、V3.1 文件保持不变，Dashboard 仍接受旧日志。V3.1.1 的真实日志单独保存和导入，不覆盖历史记录，不自动改变 Data Gate。
