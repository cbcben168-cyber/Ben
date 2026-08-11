# M3B 多形态人工复核框架验收记录

- 状态：RED — 全仓基线存在 1 项外部阻塞
- 验收基准 commit：`82624b2fc6f3a7a4bc0d69db5adb138e906e80e3`
- 最新复验日期：2026-08-11（Asia/Shanghai）
- Flat Base Detector SHA-256：`ee2c4f45026266b95a2e8759ed609a4523b713aa9bd9905447493ba8dbdd0a34`
- 33 只 Futu cache 聚合 SHA-256：`e25e78772eef37020741867bcc862512724971a8244c340227569aa28950b46c`
- legacy 源文件 SHA-256（前后相同）：`de4ed5fa0b0ab07816b096ae98e1a2427346d186c3acba6c947bc1012c73ec8c`

## 自动化验证

- [x] `pytest tests/pattern_finder -q`：122 passed。
- [ ] `pytest -q`：657 passed, 1 failed。唯一失败为用户已有、未跟踪的 `.agents/skills/developing-with-streamlit` 被 `tests/skills/test_skill_contracts.py` 判定为额外项目技能；本次未修改该目录或测试。
- [x] `git diff --check`：通过。
- [x] 固定 2026-08-07 缓存通过显式 `PATTERN_FINDER_AS_OF_UTC=2026-08-10T04:00:00+00:00` 完成跨日期复验；未设置时页面仍使用真实当前 UTC。

## Streamlit 实际人工验收

使用 Python 3.14、Streamlit 本地服务和 Playwright 真实浏览器完成；2026-08-11 复验使用 `%TEMP%/m3b-manual-acceptance-82624b2` 隔离目标文件，并通过项目 `src` 路径启动。

- [x] 首页、今日扫描、图表复核及侧栏导航主要文字为中文。
- [x] 两个形态选择器都只有“平底形态”。
- [x] 电脑 YES 显示“这段价格结构是否像一个平底形态？”。
- [x] 电脑 NO 显示“是否存在电脑漏掉的明显平底形态？”。
- [x] 人工控件显示“针对平底形态的人工判断”，明确评价对象。
- [x] 仅显示 Flat Base V1 的 11 个新原因标签。
- [x] “不像”缺少原因标签时显示错误且未生成目标文件。
- [x] “其他”缺备注由 AppTest 与模型测试确认不能保存。
- [x] 合法“电脑 YES + 人工不像 + 结构不像平底”保存为“疑似误报”，隔离 JSONL 恰好追加一行。
- [x] 三条 legacy 记录全部迁移，旧标签原样保留；实际历史记录数为 3。
- [x] 重复迁移结果为 `migrated=0, already_migrated=3, ledger_repaired=0`。
- [x] 页面不存在 Rounded Base、Compression、READY Detector、Score、Outcome 或 ML 能力。
- [x] 2026-08-11 真实浏览器复验：AAPL 显示电脑“是”及“这段价格结构是否像一个平底形态？”，MSFT 显示电脑“否”及“是否存在电脑漏掉的明显平底形态？”。
- [x] 2026-08-11 真实浏览器故意选择“不像”但不选原因标签，页面明确提示“勉强像或不像必须至少选择 1 个原因标签”，隔离文件未因该操作追加记录。

## 不可变性复核

- [x] Flat Base Detector 哈希未变。
- [x] 33 只 Futu cache 数量与聚合哈希未变。
- [x] legacy 源文件字节未变。
- [x] 实施 diff 不包含 `flat_base.py` 或行情 cache。

## 阻塞说明

在不删除或修改用户已有未跟踪目录 `.agents/skills/developing-with-streamlit` 的前提下，全仓测试无法达到零失败。因此本记录保持 RED，实施代码本身的专项回归和真实 Streamlit 流程均已通过。
