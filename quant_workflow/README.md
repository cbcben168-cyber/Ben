# 富途量化半手动研究入口

先看 [完整流程与筛选 SOP](WORKFLOW_SOP.md)，再看 [当前执行结果](STATUS.md)。
每次回测使用 [记录模板](RECORD_TEMPLATES.md)。目前处于环境/数据诊断阶段，尚无策略准入或收益结论。

## 现在需要你在牛牛做的一步

1. 在富途牛牛「量化」中新建 **Python 代码策略**，命名 `SPY_DATA_PROBE_V1`。
2. 将 [platform_data_probe.py](platform_data_probe.py) 全文复制到编辑器，使用平台提供的代码检查功能。
3. 只进入 **历史回测**，运行标的选择 **SPY**；只设置一个驱动标的。
4. 触发设置为 **每根 5 分钟 K 线运行一次**，交易时段选择 **正常交易时段 RTH**。
5. 开始与结束日期都选 **2026-10-06（美东交易日）**。如果界面采用结束日不包含规则，调整至完整包含该交易日并记录实际范围。
6. 保留平台默认初始资金并记录；这份探针不含任何下单或账户接口，订单数应为 0。
7. 运行后提供：牛牛版本、触发/日期设置、开盘附近前三条和收盘附近后三条 `FUTU_DATA_PROBE` 日志、全部异常；可以复制完整日志时优先提供完整日志。
8. 若编辑器报错，提供报错文字和行号，先解决兼容性，不切换到实盘运行来尝试。

日志 `trigger_time_utc` 是历史模拟时钟，不是 K 线源时间。
字段 `select=2` 为倒数第二根；5m 触发采样的 1m 只是一根快照，**不是完整的每分钟历史记录**。
开盘的上一根可能属于前一天；日末最后一根可能没有下一次 RTH 触发供采样。日志条数不能直接当全天 K 线覆盖数。
`qualification` 和 `bar_completion` 刻意保持 `NOT_VERIFIED`：本地测试和正常打印均不能证明数据完成状态、无前视或全区间质量。
`error_count` 为累计异常快照数；零成交量需要调查，不自动补值。缺失字段保存 null，不当作 0。

## 本地 OpenD 单日抽查（已完成一次，结果见 STATUS）

前置依赖：已有 `futu-api`、`pandas`、`numpy`、`exchange-calendars`；OpenD 已登录并在 `127.0.0.1:11111` 监听。
不自动安装或修改全局依赖。以下从仓库根目录运行，输出目录必须不存在：

```powershell
py -3.14 quant_workflow/opend_data_probe.py --date 2026-10-06 --output quant_workflow/artifacts/spy-20261006-new
```

每次显式命令只请求一个已完成交易日的 1m/5m 数据，最多各四页，无重试、订阅或订单。
生成 `1m.csv`、`5m.csv`、`report.json`；后者包含版本、口径、UTC 时间、原始文件 SHA256 和异常示例。
`SAMPLE_CHECKS_PASS` 返回 0，其余返回非零；`FAILED_DATA` 是检测出的数据问题，不应通过扩大容差使进程变绿。
现有目录拒绝覆盖；原始 `time_key` 保留供应商标签，检查时才转 UTC。
原始数据仅存本地被忽略的 `artifacts/`，不推送 GitHub。

## 本地验证

```powershell
$env:PYTHONPATH='src'
py -3.14 -m pytest tests quant_workflow/tests -q
git diff --check
```

平台探针的本地测试使用接口桩，只验证逻辑与错误处理，**不代表已在富途客户端执行成功**。
下一阶段是取得平台日志、核对输入口径与数据问题，然后再交付 EMA 基线；不跳过关卡运行三种策略。
