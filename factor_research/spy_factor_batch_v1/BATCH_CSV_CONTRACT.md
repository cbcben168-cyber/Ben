# FUTU_FACTOR_BATCH_V1 CSV 合同

## 封装

富途导出的每个日志正文必须包含：

```text
FUTU_FACTOR_BATCH_V1|{JSON object}
```

看板使用标准 CSV 解析器读取整行，再从标记位置解析首个完整 JSON 对象；JSON 内逗号不会被当成业务列。原始 CSV 只读保存，以文件 SHA256 去重。

## 批次身份

每条事件共同包含：

- `contract_version=2.0`
- `batch_id`、`run_id`
- S0：`strategy_version=FUTU_BATCH_FACTORS_V1`
- TRAIN：`strategy_version=FUTU_BATCH_FACTORS_TRAIN_V1`
- `strategy_hash`：规范化策略源码 SHA256
- S0：`parameter_version=C1-SIX-FACTOR-S0-V1`
- TRAIN：`parameter_version=C1-SIX-FACTOR-TRAIN-20251001-20260630-V1`
- `symbol=US.SPY`、`timeframe=5m`、`session=RTH`、`select=2`
- `timezone=America/New_York`

身份字段在同一 CSV 内必须完全一致，否则整批拒绝。

`definition_hash` 是下列 UTF-8 规范字符串的 SHA256：

```text
F001:C0>EMA20_0|F002:EMA20_0>EMA20_3|F003:C_1<=EMA20_1_AND_C0>EMA20_0|F004:C0>MAX_H_1_TO_H_5|F005:C_2<C_1<C0|F006:C0>O0_AND_BODY_RANGE>0.60
```

F004 的历史高点严格使用 `select=3..7`，即连续的 RTH 历史 K 线；交易日开盘初段可能引用上一交易日尾部 K 线。S0 必须用实际富途日志确认这一索引行为，不能把本地 stub 当作平台通过。F006 零振幅记录为 `INVALID/null`，导入时作为缺失测量排除，绝不能改成 `0` 或 `FAIL`。

## 事件

### `RUN_START`

必须且只能有一条。包含研究分区、计划日期、六个因子 ID、`definition_hash`、三个 horizon、无订单及禁用 Volume 声明。

### `FACTOR_EVENT`

每个有效信号时点一条，包含：

- `signal_id`、ET/UTC 时间、`signal_close`
- `f001_state` 至 `f006_state`：`PASS`、`FAIL` 或 `INVALID`
- `f001_value` 至 `f006_value`
- `r3/r6/r12`
- 每个 horizon 的目标 ET/UTC 时间和目标 close
- `price_use=NON_EXECUTABLE_CLOSE_TO_CLOSE`

看板复算 `target_close / signal_close - 1`，并验证目标时间严格为 15/30/60 分钟。任何字段缺失、重复事件、收益不一致或目录哈希不符都会整批拒绝；不允许只导入部分因子。

### `DAY_END`

每个交易日一条，记录信号数、完整事件数、无效测量数、未成熟队列和错误数。非 `COMPLETE` 会令整个批次为 `INCOMPLETE`。

### `RUN_END`

必须且只能有一条且状态为 `COMPLETE`，否则批次不能进入有效比较。

### TRAIN专用预热审计

TRAIN必须包含一条 `WARMUP_AUDIT`，声明实际首个观察、正式统计前K线数、平台EMA20、从系统起点递推的EMA20及短预热敏感性EMA20。每个TRAIN事件同时保存三组F001–F003状态；`RUN_END`的差异计数必须能由事件逐条复算。

TRAIN还必须严格匹配187个冻结交易日、12,083个共享事件和36,249条共享未来收益标签。`2025-11-28`及`2025-12-24`各29个事件，其余185日各65个事件。日期、日内网格或任一计数不一致时整批拒绝。

### `ERROR`

保留平台读取、漏触发、跨日残留等错误。存在任何 ERROR 时批次为 `INCOMPLETE`。

## 数据库展开

一个批量 CSV 在单个 SQLite 事务中展开为 F001–F006 六个逻辑 `research_runs`。六个跑次共享源文件和研究范围，但分别保存 PASS/FAIL 信号、三个 horizon 标签和统计。若版本未登记、因子集合不全或数据库已有部分批次状态，则整批失败，不生成可排序的部分排行。
