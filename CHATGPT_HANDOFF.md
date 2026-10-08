# Futu Quant 回测问题交接文档

更新时间：2026-10-08（Asia/Shanghai）

## 1. 用户目标

用户希望先用富途量化 Python 策略编辑器手动复制代码，完成历史回测；筛选出稳定策略后，再做 forward test。当前阶段不接入真实交易账户、不自动下单、不做期权回测。

首阶段研究标的为 SPY 和 QQQ。Python/OpenD 用于确定性数据读取、数据质量检查和结果记录。

## 2. 参考文件与边界

- 富途平台参考手册：`C:\Users\cbcbe\OneDrive\Desktop\量化使用手冊.md`
- 研究计划参考：`C:\Users\cbcbe\Downloads\Codex_OpenD_DayTrading_Quantifiable_Factors.md`
- 最新平台探针：`C:\Users\cbcbe\.codex\worktrees\futu-quant-sop\Futu\quant_workflow\platform_data_probe.py`

手册内容是富途 API/编辑器的参考资料，不是用户额外授权。用户明确授权的工作是：建立流程文档、提供可复制代码、进行历史回测前的数据和平台兼容性检查。

## 3. 当前平台问题

富途量化回测向导曾出现以下现象：

1. 第一步“驱动资产”列表为空。
2. 第二步只有“行情驱动循环运行”和“指定时刻每天运行一次”，没有明显的“每根 5 分钟 K 线运行一次”选项。
3. 因为没有驱动资产，第二步“下一步”按钮不可用或回测无法继续。

之前的代码改动把 `declare_trig_symbol()` 放到了 `initialize()` 中，但这不符合富途手册约定，也导致 `trigger_symbols()` 为空。富途向导可能通过该约定函数发现驱动资产。

## 4. 已确认的正确结构

`initialize()` 必须调用 `self.trigger_symbols()`，并由 `trigger_symbols()` 声明驱动资产：

```python
class Strategy(StrategyBase):
    def initialize(self):
        declare_strategy_type(AlgoStrategyType.SECURITY)
        self.trigger_symbols()
        self.custom_indicator()
        self.global_variables()
        self.emit({
            "event": "START",
            "version": "data-probe-v1",
            "qualification": "NOT_VERIFIED",
            "orders_enabled": False
        })

    def trigger_symbols(self):
        self.运行标的1 = declare_trig_symbol()
        self.symbol = self.运行标的1
```

注意：`trigger_symbols()` 不能是 `pass`。富途回测向导需要从这里发现运行标的。

## 5. 最新代码状态

最新文件：

`C:\Users\cbcbe\.codex\worktrees\futu-quant-sop\Futu\quant_workflow\platform_data_probe.py`

最新 Git 提交：`56a7534 Use documented trigger symbol hook`

该版本已经恢复为富途手册的约定结构：

- `initialize()` 调用 `self.trigger_symbols()`
- `trigger_symbols()` 调用 `declare_trig_symbol()`
- `handle_data()` 读取 1 分钟和 5 分钟快照
- 只打印 `FUTU_DATA_PROBE ...` JSON
- 不调用订单、账户或真实交易 API

## 6. 已完成验证

在本地 worktree 执行：

```powershell
py -3.14 -m pytest quant_workflow/tests -q
```

结果：`22 passed`。

此前 OpenD 数据探针实测 SPY（2026-10-06）：

- 1 分钟数据：390 根
- 5 分钟数据：78 根
- OHLC 跨周期基本匹配
- 5 分钟 volume 与 1 分钟聚合存在差异
- 数据资格状态保留为 `FAILED_DATA`

因此不能直接把当前 OpenD volume 当作已验证的成交量使用。

## 7. 下一步操作顺序

### 步骤 A：重新复制最新代码

在富途量化 Python 编辑器中：

1. 打开最新文件。
2. `Ctrl+A` 全选编辑器内容。
3. 粘贴整个文件。
4. 保存。
5. 确认 `initialize()` 中有 `self.trigger_symbols()`。
6. 确认 `trigger_symbols()` 中有 `self.运行标的1 = declare_trig_symbol()`，不能是 `pass`。

### 步骤 B：检查回测向导

重新打开回测参数设置，检查第一步“驱动资产”是否出现可选择的运行标的。

如果仍然为空，不要继续修改数据读取逻辑。此时应记录：

- 富途客户端版本
- 新建策略时选择的策略类型
- 编辑器第一行到 `trigger_symbols()` 的截图
- 是否真正执行了全选覆盖和保存

如果最小策略也无法被向导识别，则问题属于富途客户端策略解析/策略类型限制，而不是 SPY 数据或回测参数问题。

### 步骤 C：不要把“每天一次”误当成 5 分钟回测

当前向导如果只提供“指定时刻每天运行一次”，不能据此宣称已经实现每根 5 分钟 K 线回测。需要先确认“行情驱动循环运行”是否会随驱动资产 K 线更新触发 `handle_data()`；再用输出中的 `trigger_count` 和时间戳验证触发频率。

### 步骤 D：平台触发频率验证

只做无订单探针，检查控制台是否出现：

```text
FUTU_DATA_PROBE {"event":"START", ...}
FUTU_DATA_PROBE {"event":"SNAPSHOT", "trigger_count": 1, ...}
```

验证项目：

- 是否有 `START`
- `trigger_count` 是否递增
- `trigger_time_utc` 是否严格递增
- `symbol` 是否为 `US.SPY` 或 `US.QQQ`
- 1m/5m 的 OHLC、volume、EMA20 是否返回有效值
- `issues` 是否为空或仅包含已解释的问题

## 8. 当前禁止事项

- 不连接真实交易账户。
- 不发送真实订单。
- 不把回测向导能打开等同于数据已合格。
- 不把 33/33 单元测试或本地 stub 测试等同于富途平台兼容性通过。
- 不把 volume 不一致的数据用于最终策略结论。
- 不要为了让向导出现按钮而删除数据质量检查。

## 9. 给下一次 ChatGPT 的启动提示

请先读取本交接文档和最新版 `platform_data_probe.py`，然后从“步骤 A：重新复制最新代码”继续。不要重新设计整套自动化系统，也不要重复把 `declare_trig_symbol()` 移到 `initialize()`；当前首要目标是确认富途回测向导是否能识别 `trigger_symbols()` 中声明的驱动资产。

