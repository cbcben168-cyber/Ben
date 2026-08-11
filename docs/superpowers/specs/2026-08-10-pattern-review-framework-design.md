# Pattern Research System — 多形态人工复核框架设计蓝图

**文档版本**：V1  
**日期**：2026-08-10  
**当前阶段**：Phase 1 / M3B 验收修正  
**状态**：设计已冻结，待实施计划  
**文件路径**：`docs/superpowers/specs/2026-08-10-pattern-review-framework-design.md`

## 1. 设计目标

当前系统已经具备 Flat Base（平底形态）检测与人工复核能力，但人工复核逻辑仍明显写死在 Flat Base：

- 验证模型名为 `FlatBaseValidation`
- 保存文件名为 `flat_base_validation.jsonl`
- 电脑判断字段为 `computer_flat_base`
- 原因标签为一套全局 `REASON_TAGS`
- Chart Review 表单围绕 Flat Base 固定
- 页面中的“像 / 勉强像 / 不像”没有明确说明“像什么”

本次设计的目标不是增加新 Detector，而是把人工复核层改造成一个**可扩展的多形态复核框架**。

完成后：

1. 当前仍然只启用 Flat Base。
2. 后续增加 Rounded Base、Compression、READY 或其他形态时，不需要重写人工复核、历史保存、筛选与结果判定逻辑。
3. 每种形态拥有自己独立的：
   - 中文名称
   - 判断问题
   - 判断说明
   - 原因标签
   - 诊断字段定义
4. 用户界面统一中文。
5. 人工标签含义稳定，避免污染未来训练数据。
6. 不修改 `phase1-v1` Flat Base Detector 的任何数学参数。

## 2. 本次明确不做什么

本设计只处理“复核框架”和“界面语义”。

本轮禁止实现：

- Rounded Base Detector
- Compression Detector
- READY Detector
- 新的 Candidate Scanner
- 0–100 Rule Score
- 正式 1–5 Human Score
- Shape Model
- Outcome Model
- Machine Learning
- Future 5D / 10D / 20D Outcome
- Optuna
- YOLO / Image AI
- IBKR
- 自动交易
- Flat Base 参数优化
- Futu Universe 再扩容
- Futu Cache 结构改造

## 3. 核心架构决策

采用 **Pattern Registry（形态注册表）配置式架构**。

### 不采用方案 A：每一种形态写一套人工复核代码

问题：

- Flat Base、Rounded Base、Compression 会不断复制页面和保存逻辑。
- 原因标签容易混用。
- 数据结构越来越难维护。

### 不采用方案 C：完整 Plugin / Class 插件系统

问题：

- 当前只有 1 个真实 Detector，过度设计。
- 增加复杂度和 Token / 维护成本。

### 选择方案 B：Pattern Registry

核心思想：

> Detector 负责“电脑怎么判断”；  
> Pattern Registry 负责“人工到底在判断什么、看到什么、为什么认为不像”。

统一人工复核系统只认一个 `pattern_type`，其他内容从 Registry 读取。

## 4. 总体结构

```text
Pattern Research System
│
├── Detectors
│   ├── flat_base / phase1-v1          ← 当前已实现
│   ├── rounded_base                   ← 未来
│   └── compression                    ← 未来
│
├── Pattern Registry
│   ├── flat_base profile              ← 当前唯一启用
│   ├── rounded_base profile           ← 未来注册
│   └── compression profile            ← 未来注册
│
├── Today Scan
│   └── 根据当前 pattern_type 显示对应字段
│
├── Chart Review
│   ├── 当前复核形态
│   ├── 当前 Detector 诊断
│   ├── 图表覆盖层
│   ├── 像 / 勉强像 / 不像
│   ├── 当前形态专属原因标签
│   └── 备注
│
└── Pattern Validation Store
    └── pattern_validation.jsonl
```

## 5. Pattern Registry 定义

每个可复核形态必须注册一份 Profile。

概念字段如下：

| 字段 | 作用 |
|---|---|
| `pattern_type` | 稳定机器 ID，例如 `flat_base` |
| `display_name_zh` | 中文名称，例如“平底形态” |
| `display_name_en` | 英文名称，例如 `Flat Base` |
| `review_question_yes` | 电脑 YES 时人工要回答的问题 |
| `review_question_no` | 电脑 NO 时人工要回答的问题 |
| `review_help` | 明确告诉用户不要判断未来收益 |
| `reason_tags` | 当前形态专属原因标签 |
| `diagnostic_fields` | 当前形态要显示的诊断字段 |
| `overlay_capabilities` | 是否支持识别区间 / 支撑 / 阻力等 |
| `enabled` | 当前是否已正式启用 |

当前唯一启用 Profile：

```text
pattern_type = flat_base
display_name_zh = 平底形态
display_name_en = Flat Base
enabled = true
```

未来形态可以预留设计示例，但不能在本轮注册为 `enabled=true`，避免页面出现尚未实现的 Detector。

## 6. Flat Base 人工判断定义

### 6.1 Computer = YES

页面必须明确显示：

> **人工复核目标：平底形态**  
> 请主要评价图中 Detector 选择的“底部识别区间”：  
> **这段价格结构是否像一个平底形态（Flat Base）？**

人工只看 T0 及之前已经存在的 K 线。

不得考虑：

- 以后会不会涨
- 后面有没有突破
- 突破成功与否
- 后续收益
- 财报结果
- 未来 5D / 10D / 20D

### 6.2 Computer = NO

页面必须明确显示：

> **人工复核目标：平底形态**  
> 电脑当前判断为“否”。  
> 请检查最近 25–90 个交易日中，是否存在电脑漏掉的明显平底形态。

这样才能发现 False Negative（漏报）。

## 7. 人工标签统一语义

所有形态复用三种人工标签：

### 像

> 明显符合当前正在复核的形态。

### 勉强像

> 存在当前形态的主要轮廓，但质量一般、带明显瑕疵、或属于边界案例。

不是“不知道”。

### 不像

> 人工认为当前结构不属于正在复核的形态。

## 8. 自动 Validation Result

系统根据：

```text
Computer Result + Human Label
```

自动生成工程验证结论。

| Computer | Human | Validation Result |
|---|---|---|
| YES | 像 | 一致命中 |
| NO | 不像 | 一致排除 |
| YES | 不像 | 疑似误报 |
| NO | 像 | 疑似漏报 |
| YES / NO | 勉强像 | 边界案例 |

该字段：

- 不是 Human Score
- 不是 Rule Score
- 不是 ML Target
- 只是 M3B / Phase 1 工程验证结果

内部稳定 ID 固定为：

```text
true_positive_like
true_negative_unlike
possible_false_positive
possible_false_negative
borderline
```

用户界面只显示中文。

## 9. 原因标签必须按形态配置

原因标签不能再是全局常量。

必须由当前 `pattern_type` 对应 Profile 提供。

## 10. Flat Base 专属原因标签 V1

Flat Base V1 原因标签固定为：

1. `底部区间太深`
2. `底部持续时间太短`
3. `低点区域不集中`
4. `横盘稳定性不足`
5. `整体仍明显向上`
6. `整体仍明显向下`
7. `波动区间过宽`
8. `阻力区域不清晰`
9. `底部测试次数不足`
10. `结构不像平底`
11. `其他`

标签行为：

- `像`：不要求原因标签，允许为空；如果提供标签，仍必须属于当前 Pattern Profile。
- `勉强像`：强制至少选择 1 个当前 Pattern Profile 的原因标签。
- `不像`：强制至少选择 1 个当前 Pattern Profile 的原因标签。
- 选择 `其他` 时，`note.trim()` 强制非空。
- 上述规则只约束新产生的 `PatternValidation`；legacy migrated record 按第 15 节的兼容规则处理。

## 11. 未来 Rounded Base 原因标签示例

本轮不实现 Rounded Base，只定义未来扩展方式：

- 左侧下降不明显
- 中部没有明显转平
- 底部过尖，接近 V 型反转
- 底部不够圆滑
- 右侧回升不足
- 左右结构严重不对称
- 底部过深
- 右侧结构没有改善
- 结构不像圆底
- 其他

这些标签不能出现在当前 Flat Base 页面。

## 12. 未来 Compression 原因标签示例

未来 Compression Profile 可以有：

- ATR 没有明显收缩
- 成交量没有明显萎缩
- 价格区间没有明显收窄
- 收缩持续时间不足
- 波动反复扩大
- 价格结构过于松散
- 结构不像有效压缩
- 其他

同样不能出现在 Flat Base 页面。

## 13. 通用 Validation 数据结构

现有 Flat Base 专用结构应升级为通用记录。

字段固定为：

```text
recorded_at_utc
symbol

pattern_type
pattern_display_name

detector_version
scan_as_of_date

computer_result
human_label
validation_result

reason_tags
note

review_window_start
review_window_end

diagnostics

migration_provenance
```

新产生的 `PatternValidation` 必须满足完整的新 schema：

- `pattern_type`、`pattern_display_name`、`computer_result`、`human_label`、`validation_result` 必须存在且有效。
- `review_window_start` 与 `review_window_end` 必须存在并形成有效区间。
- `diagnostics` 必须包含当前 Pattern Profile 要求的诊断字段。
- `migration_provenance` 必须为 `null`。

只有从旧 schema 迁移且确实无法推导的字段才允许为 `null`。该例外不能用于放宽新记录的完整性要求。

### diagnostics

`diagnostics` 使用 JSON Object / Mapping。

原因：

不同形态有不同诊断字段。

Flat Base 示例：

```text
base_length
base_depth
bottom_tests
normalized_slope
support
resistance
```

Rounded Base 未来可能是：

```text
left_slope
middle_slope
right_slope
quadratic_r2
higher_low
```

不能为了兼容未来形态，在顶层不断增加几十个专用字段。

### migration_provenance

`migration_provenance` 只用于 legacy migrated record，新记录必须为 `null`。迁移记录中保存：

```text
source_path
source_line_number
source_line_content_sha256
migration_fingerprint
```

`migration_fingerprint` 按以下规范确定性计算：

```text
normalized_source_path = 仓库相对 POSIX 路径
source_line_content_sha256 = sha256(旧 JSONL 原始行 UTF-8 字节，不含换行符)
migration_fingerprint = sha256(
    UTF8(normalized_source_path + "\n" + 十进制 source_line_number + "\n" + source_line_content_sha256)
)
```

不得使用绝对路径或整个源文件 content hash 作为逐记录幂等依据。

## 14. Validation Store

默认路径从：

```text
data/processed/pattern_finder/manual_validation/flat_base_validation.jsonl
```

升级为：

```text
data/processed/pattern_finder/manual_validation/pattern_validation.jsonl
```

所有形态共用一个 append-only JSONL。

每条记录通过：

```text
pattern_type
```

区分形态。

历史规则：

- 只追加，不覆盖旧记录。
- 同一股票、同一形态、同一 Detector Version、同一 scan date 可以存在多次人工复核。
- UI 默认展示最新一条。
- History Count 保留全部人工修改历史。

最新记录与 History Count 的查询 key 固定为：

```text
(symbol, pattern_type, detector_version, scan_as_of_date)
```

## 15. 旧 Flat Base 验证记录兼容

实现前必须先检查旧文件：

```text
flat_base_validation.jsonl
```

### 情况 A：文件不存在或为空

直接使用新的：

```text
pattern_validation.jsonl
```

无需迁移。

### 情况 B：已经存在记录

不得删除。

采用可重复执行、可测试、逐记录幂等迁移：

- 保留旧文件，不删除、不覆盖、不改写。
- 每一条旧记录都必须迁移；不得按 `(symbol, pattern_type, detector_version, scan_as_of_date)` 或其他业务 key 去重。
- 保留原 `recorded_at_utc`、`symbol`、`detector_version`、`scan_as_of_date`、`human_label`、`reason_tags` 与 `note`。
- 自动补 `pattern_type=flat_base`。
- 自动补 `pattern_display_name=平底形态`。
- 将旧 `computer_flat_base` 确定性转换为新 `computer_result`。
- 根据 `computer_result + human_label` 确定性重新计算 `validation_result`，不得从旧文件读取或人工指定。
- 将旧 `base_length`、`base_depth`、`bottom_tests`、`normalized_slope` 原样移入新 `diagnostics`。
- `review_window_start`、`review_window_end` 以及其他确实无法从旧 schema 推导的信息允许为 `null`。

旧 Reason Tags 规则：

- 原样保留，不映射、不翻译、不静默改写。
- legacy migrated record 豁免当前 Pattern Profile 的 reason tag 枚举校验。
- 该豁免只由非空且有效的 `migration_provenance` 触发；普通新记录不得使用。
- 旧记录即使不满足新记录“勉强像 / 不像至少一个原因标签”或“其他必须填写备注”的规则，也必须保留。

迁移账本：

```text
data/processed/pattern_finder/manual_validation/pattern_validation_migration_ledger.jsonl
```

- 账本按 `migration_fingerprint` 记录已处理的源记录。
- 每条账本记录包含 `migration_fingerprint`、`source_path`、`source_line_number`、`source_line_content_sha256` 与 `migrated_at_utc`。
- 写入顺序必须先追加目标 `pattern_validation.jsonl`，再追加 migration ledger。
- 每次迁移同时检查目标记录中的 `migration_provenance.migration_fingerprint` 与账本。
- 如果目标记录已存在但账本条目缺失，只补写账本，不重复追加目标记录。
- 同一旧记录重复执行迁移不会重复导入。
- 旧文件以后仅追加新记录时，只迁移新增行；整个旧文件 hash 改变不得导致已迁移记录再次导入。
- 如果账本中同一 `source_path + source_line_number` 的行内容 hash 与当前旧文件不一致，迁移必须停止并报告旧历史被修改，不得把修改后的行当作新增记录导入。
- 任一失败必须显式报告，不得跳过或静默丢弃旧记录。

## 16. Today Scan 中文化与多形态入口

页面名称：

```text
今日扫描
```

页面顶部增加：

```text
当前查看形态：[ 平底形态 ▼ ]
```

当前只有一个可选项：

```text
平底形态
```

未来 Rounded Base Detector 完成后，Registry 中启用它，页面自动增加：

```text
平底形态
圆底形态
```

当前 Flat Base 表格必须至少包含以下中文字段：

- 股票代码
- 平底形态
- 底部周期
- 底部深度
- 底部测试次数
- 标准化斜率
- 人工形态判断
- 验证结论
- 数据质量

页面必须提供以下筛选：

- 电脑判断：全部 / 是 / 否
- 人工复核：全部 / 未复核 / 像 / 勉强像 / 不像
- 验证结论：全部 / 一致命中 / 一致排除 / 疑似误报 / 疑似漏报 / 边界案例

## 17. Chart Review 中文化与多形态入口

页面名称：

```text
图表复核
```

顶部：

```text
股票代码：[ AAPL ▼ ]

当前复核形态：[ 平底形态 ▼ ]
```

当前形态下拉只有 Flat Base。

诊断区显示：

```text
电脑判断：平底形态 = 是
检测器版本：phase1-v1
识别区间：YYYY-MM-DD ~ YYYY-MM-DD

底部周期：25 个交易日
底部深度：14.86%
底部测试次数：2
标准化斜率：...
支撑位：...
阻力位：...
```

图表保留：

- 日K（OHLC）
- 成交量
- 底部识别区间
- 支撑位
- 阻力位

技术缩写可以保留，但中文说明优先：

- 前复权（QFQ）
- ATR14
- 日K（OHLC）

## 18. 人工复核区最终文案

### 标题

```text
人工形态复核
```

### 当前对象

```text
当前评价形态：平底形态
```

### 当 Computer = YES

```text
请主要评价图中标出的“底部识别区间”。

问题：
这段价格结构是否像一个平底形态？

只根据当前及之前已经发生的K线判断。
不要考虑未来涨跌、突破是否成功或后续收益。
```

### 当 Computer = NO

```text
电脑当前未识别出平底形态。

请查看最近 25–90 个交易日：
是否存在电脑漏掉的明显平底形态？

只根据当前及之前已经发生的K线判断。
```

### 输入

```text
人工形态判断：
[ 像 ] [ 勉强像 ] [ 不像 ]

原因标签：
[ 当前形态专属标签，多选 ]

备注：
[ 文本 ]

[ 保存人工复核 ]
```

### 保存后

例如：

```text
电脑判断：是
人工判断：不像
验证结论：疑似误报
```

## 19. UI 中文化词汇表

| 当前/英文 | 中文 |
|---|---|
| Home | 首页 |
| Today Scan | 今日扫描 |
| Chart Review | 图表复核 |
| Data Source | 数据来源 |
| Fixture | 测试数据 |
| Cache / Futu | 本地缓存 / 富途 |
| Symbol | 股票代码 |
| Flat Base | 平底形态 |
| YES / NO | 是 / 否 |
| Base Length | 底部周期 |
| Base Depth | 底部深度 |
| Bottom Tests | 底部测试次数 |
| Normalized Slope | 标准化斜率 |
| Base Window | 底部识别区间 |
| Support | 支撑位 |
| Resistance | 阻力位 |
| Volume | 成交量 |
| Data Quality | 数据质量 |
| Adjustment | 复权方式 |
| Human Validation | 人工形态复核 |
| Human Label | 人工形态判断 |
| Reason Tags | 原因标签 |
| Note | 备注 |
| History | 历史记录 |
| Save Validation | 保存人工复核 |
| Detector Version | 检测器版本 |

内部字段和代码变量允许继续使用英文，避免破坏程序稳定性。

## 20. Pattern Registry 与 Detector 的边界

必须保持：

```text
Detector ≠ Review Profile
```

Detector 负责：

- 数学算法
- 参数
- YES / NO
- diagnostics
- selected window
- overlay values

Review Profile 负责：

- 中文名称
- 人工判断说明
- 原因标签
- 显示字段
- 页面文案

因此：

> 修改“原因标签”绝不能改变 Detector 结果。

也不能因为人工大量选择“不像”，就在本轮自动调整 Detector 参数。

## 21. 新增形态的标准流程

未来增加一个新形态时：

1. 先独立实现并验证 Detector。
2. Detector 通过自己的 Milestone Gate。
3. 在 Pattern Registry 注册 Review Profile：
   - pattern_type
   - display name
   - review question
   - reason tags
   - diagnostics display map
4. 统一 Today Scan / Chart Review 自动出现该形态。
5. 统一 Validation Store 自动保存：
   - `pattern_type = 新形态`

无需复制整套人工复核逻辑。

## 22. 测试要求

本次实现必须先写失败测试再改生产代码。

至少覆盖：

### Pattern Registry

- Flat Base Profile 可正确加载
- 未注册 pattern_type 明确报错
- disabled pattern 不出现在 UI 可选项
- 原因标签来自当前形态，不是全局常量

### Validation

- 通用 `PatternValidation` 可保存 Flat Base
- key 包含 `pattern_type`
- validation_result 自动正确生成
- `勉强像` 始终为边界案例
- append-only
- latest record 正确
- legacy migration 不丢数据

### UI

- 页面为中文
- 当前形态明确显示“平底形态”
- YES 页面明确提示评价识别区间
- NO 页面明确提示寻找漏判
- Flat Base 只显示 Flat Base 原因标签
- 页面没有 Rounded Base Detector 功能
- 页面没有未来 Outcome / Score / ML 字段

### Regression

- Flat Base Detector 输出完全不变
- `phase1-v1` 阈值完全不变
- M3B 当前 33 只 cache 不被修改
- 现有数据质量逻辑不变

## 23. 验收标准

只有满足全部条件才允许 M3B 最终 PASS：

1. UI 面向用户的主要文字已中文化。
2. 页面明确显示“当前复核形态”。
3. “像 / 勉强像 / 不像”的评价对象不再模糊。
4. Flat Base 原因标签为 Flat Base 专属。
5. 原因标签由 Pattern Registry 提供。
6. Validation 数据结构不再写死 Flat Base。
7. Validation Store 支持多个 `pattern_type`。
8. 当前实际启用的 Detector 仍只有 Flat Base。
9. Flat Base Detector 代码与冻结数学参数无变化。
10. 当前 33 只行情 cache 无变化。
11. 自动测试全绿。
12. Streamlit 实际打开并完成人工复核流程。
13. PR #6 仍保持未合并，直到人工最终确认。

## 24. 本轮文件边界

实现范围：

```text
src/tv_quant/pattern_finder/
├── pattern_registry.py     # 形态配置与查询
├── validation.py           # 通用人工复核记录与存储
├── review.py               # Today Scan / Review 数据关联
├── flat_base.py            # 不修改 Detector 数学规则
└── ...

app/pages/
├── 1_Today_Scan.py
└── 2_Chart_Review.py
```

不要求为了形式强制新增文件；如果现有代码边界更合适，可以保持最小改动。

但必须避免继续把新的形态配置硬编码进 Streamlit 页面。

## 25. 最终设计结论

本次 M3B 验收修正采用：

> **Pattern Registry + 通用 Pattern Validation Store + 当前形态专属 Reason Tags + 全中文 UI**

当前唯一正式启用：

> `flat_base / 平底形态 / phase1-v1`

未来保留扩展能力，但本轮不实现任何其他 Detector。

核心原则：

> **现在只解决今天真实需要的问题，但把边界设计好，使未来增加新形态时不需要推倒重来。**

## 26. 长期强制用户交付说明

从本设计生效后，每一次功能修改、Bug 修复、Detector 修改、UI 修改、数据层修改或 Milestone 完成后的最终交付报告，都必须包含以下完整章节：

```text
# 用户交付说明
```

该章节不是可选项。不能只提供文件名、函数名、commit、测试数量或面向开发者的实现摘要。交付说明必须面向普通用户，使用可直接照做的中文，并固定包含以下七部分。

### 1. 这次改了什么

必须先用普通用户能理解的中文说明：

- 改了什么；
- 为什么改；
- 改完有什么实际区别。

不得只列文件名、函数名或 commit。

### 2. 我怎么使用

必须给出可直接执行的完整操作路径：

- Windows 启动命令；
- 进入哪个页面；
- 点击哪个功能；
- 选择什么；
- 实际操作顺序。

### 3. 我怎么人工测试

必须给出不超过 10 项的 checklist。每一项都必须同时说明：

- 用户要做什么；
- 正常情况下应该看到什么。

不得使用“检查功能是否正常”之类无法验收的描述。

### 4. 如果失败代表什么

必须列出本次改动最重要的异常情况，并帮助用户初步区分：

- 环境问题；
- 数据问题；
- 代码问题；
- Detector 问题。

至少解释与本次范围相关的页面打不开、没有数据、Data Quality FAIL、UI 行为异常分别可能代表什么。

### 5. 给 ChatGPT 的改良材料

必须明确说明用户应该截图什么以及复制什么数据。

截图说明应根据本次范围指定页面、股票或案例，包括适用时的 YES、NO、误报、漏报和边界案例。

同时必须生成一段可以直接粘贴给 ChatGPT 的中文摘要。对于 Pattern Detector，该摘要至少包含：

- `pattern_type`；
- `detector_version`；
- sample count；
- Computer YES / NO；
- Human 像 / 勉强像 / 不像；
- 一致命中；
- 一致排除；
- 疑似误报；
- 疑似漏报；
- 边界案例；
- 最常见原因标签。

如果当前样本不足，必须明确写“样本不足”，不得用空值或省略字段掩盖。

### 6. 最值得 ChatGPT 分析的案例

对于 Detector 相关改动，必须自动挑选并告诉用户：

- 最典型正确案例；
- 最明显误报；
- 最明显漏报；
- 典型边界案例；
- 接近 Detector 阈值的案例。

如果本次改动不是 Detector，则必须改为挑选最能暴露本次功能问题的案例。任何类型不存在可选样本时，都必须明确说明“样本不足”或“当前没有该类案例”。

### 7. 最终状态

用户交付说明最后必须逐行报告：

```text
BLOCKER = ?
HIGH = ?
AUTOMATED_TEST = PASS / FAIL
MANUAL_TEST_REQUIRED = YES / NO
```

如果需要人工测试，还必须报告：

```text
READY_FOR_USER_TEST = YES / NO
```

在用户尚未完成人工测试前，Codex 不得自行声称最终 PASS。此时只能报告自动化验证状态、已知风险以及是否已经准备好交给用户测试。
