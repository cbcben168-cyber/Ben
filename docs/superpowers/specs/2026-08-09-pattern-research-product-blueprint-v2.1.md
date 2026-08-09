# K线形态研究系统 V2 — 分阶段产品设计蓝图

**文档类型：** Product Design Blueprint  
**版本：** V2.1  
**日期：** 2026-08-09  
**目标项目：** `C:\Users\cbcbe\TradingCodex\tv_quant_system`  
**建议仓库路径：** `docs/superpowers/specs/2026-08-09-pattern-research-product-blueprint-v2.md`

---

# 0. 产品目标

建立一个**半自动化美股 K 线形态研究网页系统**。

系统不自动下单。

系统主要完成：

```text
自动扫描美股
↓
找出疑似目标形态
↓
人工快速查看
↓
人工评分
↓
电脑评分
↓
未来自动验证
↓
系统学习
↓
不断提高“找对形态”的概率
```

最终每 5 个交易日的使用方式应该非常简单：

```text
每 5 个交易日打开网页
↓
系统更新到最新日线并运行完整扫描
↓
看到约 20 个候选
↓
快速看图
↓
评分 / 标记
↓
完成
```

之后系统自动处理：

```text
未来结果追踪
模型学习
历史对照
规则优化
```

## 0.1 固定运行频率

V2.1 起，完整扫描与人工复核固定为：

```text
每 5 个交易日一次
```

定义：

- `Scan Cadence = 5 Trading Days`
- 不是 5 个自然日。
- 每次扫描建立新的 `T0` 候选批次。
- 不要求每天运行全市场扫描。
- 扫描当天先把本地 OHLCV 更新到最新交易日，再开始扫描。
- 后续可以手动触发额外扫描，但必须标记 `manual_scan = true`，不得与固定周期样本混为同一实验口径。

这与 Future Outcome 的：

```text
5D
10D
20D
```

完全独立。

例如：

```text
T0 = 本次扫描日

T0 + 5 Trading Days  → Outcome 5D
T0 + 10 Trading Days → Outcome 10D
T0 + 20 Trading Days → Outcome 20D
```

因此：

> 扫描频率决定“多久生成一次新样本”；5D/10D/20D 决定“每个样本未来观察多久”。

---

# 1. 产品开发总原则

这套系统必须按阶段开发。

禁止：

```text
一次性把：
扫描
评分
AI
回测
机器学习
自动优化
全部一起开发
```

因为这样一旦结果有问题，很难知道：

```text
是数据错？
还是形态规则错？
还是评分错？
还是模型错？
还是回测错？
```

所以系统必须采用：

# Progressive Verification

即：

> 每一阶段只增加一个新的“智能层”，上一层必须先证明正确。

---

# 2. 五阶段总路线

```text
┌──────────────────────────┐
│ Phase 1                  │
│ 自动找出图形             │
│ Pattern Finder           │
└─────────────┬────────────┘
              ↓
        人工验证图形
              ↓ PASS

┌──────────────────────────┐
│ Phase 2                  │
│ 人工评分系统             │
│ Human Rating             │
└─────────────┬────────────┘
              ↓
        建立标签数据库
              ↓ PASS

┌──────────────────────────┐
│ Phase 3                  │
│ 电脑评分系统             │
│ Computer Score           │
└─────────────┬────────────┘
              ↓
        人 vs 电脑对照
              ↓ PASS

┌──────────────────────────┐
│ Phase 4                  │
│ 系统学习                 │
│ Learning Engine          │
└─────────────┬────────────┘
              ↓
       学习用户偏好
       学习未来结果
              ↓ PASS

┌──────────────────────────┐
│ Phase 5                  │
│ 其他优化                 │
│ Optimization             │
└──────────────────────────┘
```

每一阶段都必须：

1. 有可打开网页。
2. 有真实数据。
3. 有明确测试方法。
4. 有 PASS / FAIL。
5. 可独立使用。
6. 不依赖下一阶段才能证明价值。

---

# 3. Phase 1 — 自动把图形找出来

# 3.1 目标

这一阶段只解决一个问题：

> 系统能不能从大量美股中，把“可能像我们要找的底部平底 / 圆底 / 压缩形态”找出来？

这一阶段：

```text
不做人评分学习
不做机器学习
不做未来预测
不做自动优化
```

只做：

```text
数据
+
规则
+
扫描
+
网页看图
```

---

# 3.2 输入

初期股票池：

```text
NYSE
NASDAQ
AMEX
```

基础过滤：

```text
普通股
Price >= 5 USD
20D Average Dollar Volume >= 20M USD
上市时间 >= 250 Trading Days
```

排除：

```text
OTC
Warrant
Preferred
Unit
明显停牌 / 异常证券
```

---

# 3.3 数据

主数据：

```text
Futu OpenD
```

本地缓存：

```text
OHLCV Daily Bars
```

更新方式：

```text
第一次下载历史
以后在每次扫描前做增量更新
```

允许底层数据更新任务更频繁运行，但 V1 产品不要求每天执行全市场扫描。

禁止每次扫描重新下载全部历史数据。

---

# 3.4 初始形态

第一阶段只做三类：

## A. Flat Base

主要特征：

```text
底部持续 >= 25D
价格区间较窄
低点稳定
ATR下降
成交量下降
阻力明确
```

---

## B. Rounded Base

主要特征：

```text
左侧下降
中部变平
右侧上升

Left Slope < 0
Middle Slope ≈ 0
Right Slope > 0
```

额外：

```text
Quadratic curvature
Higher Low
Right Side Strength
```

---

## C. Compression / Ready

识别：

```text
底部基本完成
距离阻力较近
ATR继续压缩
成交量干枯
尚未明显突破
```

---

# 3.5 第一版扫描原则

第一阶段扫描器的目标：

# Recall 优先

宁愿：

```text
找到 100 个
其中 30 个是真的
```

也不要：

```text
只找到 5 个
全部很漂亮
```

原因：

后面系统学习需要：

```text
好案例
+
坏案例
+
边界案例
```

---

# 3.6 Phase 1 网页

只需要两个页面。

---

## 页面 A — Scan

顶部：

```text
今日日期

Universe             4,200
Eligible             2,700
Pattern Candidates     135
```

筛选：

```text
Flat
Rounded
Compression
```

候选表：

```text
Ticker
Pattern Type
Base Days
Base Depth
ATR Ratio
Volume Ratio
Resistance
Distance to Resistance
```

---

## 页面 B — Chart Review

显示：

```text
Ticker
120–250D Candlestick
Volume
Base Window
Base Low
Resistance
MA20
```

右边显示原始特征：

```text
Base Days
Base Depth
ATR Ratio
Volume Ratio
Left Slope
Middle Slope
Right Slope
Distance to Resistance
```

此时：

> 不显示任何“AI 分数”。

---

# 3.7 Phase 1 测试方法

每天随机抽：

```text
50–100 个候选
```

人工判断：

```text
真的像目标形态
勉强
完全不像
```

还必须随机抽：

```text
50–100 个没有被选中的股票
```

检查有没有明显漏掉。

---

# 3.8 Phase 1 核心指标

### Precision

候选中真正像目标形态的比例。

### Recall Proxy

人工随机抽取未入选股票时，明显目标形态被漏掉多少。

### Candidate Count

每个 5 交易日扫描批次的候选数量是否合理。

---

# 3.9 Phase 1 PASS 条件

进入 Phase 2 前必须满足：

```text
数据无明显错误

K线和 Futu / TradingView 基本一致

候选数量稳定

人工认为扫描器确实能找到大量“类似目标”的图形

没有明显系统性漏掉某一类底部
```

不用追求完美。

目标：

> “值得人工看。”

---

# 4. Phase 2 — 加入人工评分制度

# 4.1 目标

解决第二个问题：

> 在系统找到的候选里面，用户到底喜欢哪一种？

这一阶段仍然：

```text
不训练 ML
```

先建立可靠标签。

---

# 4.2 人工评分

主评分：

```text
1–5
```

定义固定：

| Score | 定义 |
|---:|---|
| 1 | 完全不是我要的 |
| 2 | 有一点像，但明显不好 |
| 3 | 可以观察 |
| 4 | 很符合 |
| 5 | 非常典型 |

---

# 4.3 优点标签

```text
底部长
底部稳定
圆底漂亮
ATR压缩
成交量干枯
Higher Low
右侧强
阻力明确
距离突破近
价格结构干净
```

---

# 4.4 缺点标签

```text
底部太短
底部太深
波动太大
成交量乱
假圆底
低点不稳定
右侧太急
离阻力太远
已经涨太多
Gap扭曲
新闻驱动
阻力不清楚
```

---

# 4.5 Review 页面升级

Phase 1 Chart Review 页面增加：

```text
你的评分
[1] [2] [3] [4] [5]

优点：
☐ ...

缺点：
☐ ...

备注：
__________

[保存并下一只]
```

---

# 4.6 保存 T0 Snapshot

当用户评分时必须冻结：

```text
Ticker
Date
OHLC
Resistance
Base Low
ATR
所有 Feature
当时图形范围
人工评分
Tags
```

以后：

```text
永不覆盖
```

---

# 4.7 增加 Before / After 数据基础

这一阶段可以开始记录未来数据。

但网页暂时主要用于：

```text
收集标签
```

未来 5 / 10 / 20D 的结果先自动存数据库。

---

# 4.8 Phase 2 每 5 个交易日工作

例如：

```text
每 5 个交易日
↓
系统找到约 100 个候选
↓
网页选择约 20 个
↓
你人工评分
↓
保存本批次 T0 Snapshot
```

每 5 个交易日人工复核约 20 个，且不要全部来自“最漂亮”的。

建议：

```text
12 Top candidates
4 Borderline
4 Random / exploration
```

---

# 4.9 Phase 2 测试

检查：

### A
人工评分是否方便。

目标：

```text
看一个图
点击评分
下一只
```

### B
同一个旧图两周以后重新评分是否接近。

### C
Snapshot 有没有未来数据泄漏。

### D
未来结果出现后，原始人工分是否仍然保持不变。

---

# 4.10 Phase 2 PASS

至少积累：

```text
300–500 个有效人工标签
```

并且：

```text
评分流程稳定
评分定义基本一致
数据没有泄漏
```

才进入 Phase 3。

---

# 5. Phase 3 — 电脑评分系统

# 5.1 目标

这一阶段先不让电脑“学习”。

先建立一个：

# Explainable Rule Score

让系统根据我们明确规定的数学条件自动打分。

---

# 5.2 为什么先 Rule Score

如果直接进入 ML：

出现：

```text
电脑评分 91
```

你却不知道为什么。

这是危险的。

Phase 3 必须先建立：

```text
透明的电脑评分
```

---

# 5.3 Computer Rule Score

示意：

| Feature | 分数 |
|---|---:|
| Base Length | 10 |
| Base Depth | 10 |
| Bottom Stability | 10 |
| Roundedness | 10 |
| ATR Compression | 10 |
| Volume Dry-up | 10 |
| Higher Low | 10 |
| Resistance Quality | 10 |
| Near Resistance | 10 |
| Right Side Strength | 10 |

总：

```text
0–100
```

---

# 5.4 每个分数必须可解释

例如：

```text
AMD

Rule Score = 84
```

下面显示：

```text
Base Length       10/10
Base Depth         8/10
Bottom Stability   9/10
Roundedness        7/10
ATR Compression    9/10
Volume Dry-up      9/10
Higher Low         8/10
Resistance         8/10
Near Resistance    8/10
Right Side         8/10
```

---

# 5.5 Phase 3 网页升级

Today Scan 页面加入：

```text
Human Score
Rule Score
Difference
```

例如：

| Ticker | Human | Computer | Gap |
|---|---:|---:|---:|
| AMD | 5 | 92 | + |
| MU | 4 | 85 | + |
| XYZ | 2 | 87 | ⚠ |

最重要的是找：

```text
Human High / Computer Low
Human Low / Computer High
```

---

# 5.6 人机差异页面

新增：

# Disagreement

分四组：

```text
A. Human High / Computer High
B. Human High / Computer Low
C. Human Low / Computer High
D. Human Low / Computer Low
```

B/C 是最重要的研究样本。

---

# 5.7 Phase 3 测试

比较：

```text
Computer Score
vs
Human Score
```

重点不是追求完全一致。

而是回答：

```text
电脑到底哪里判断错？
```

---

# 5.8 Phase 3 优化方式

这里只允许：

```text
人工修改明确规则
```

例如发现：

```text
Computer High / Human Low
```

经常因为：

```text
底部过深
```

可以重新调整：

```text
Base Depth 权重
```

所有修改：

```text
Rule V1
Rule V2
Rule V3
```

必须保留历史版本。

---

# 5.9 Phase 3 PASS

要求：

```text
电脑评分整体方向和人工评分有明显相关性
```

并且：

```text
电脑评分原因可解释
```

达到后再进入真正机器学习。

---

# 6. Phase 4 — 系统学习

Phase 4 才真正加入 Machine Learning。

必须拆成两个不同模型。

---

# 6.1 Model A — Shape Model

学习：

> 什么形态“像你要的形态”。

训练数据：

```text
Human Score
Human Tags
Pairwise Preference
```

输入：

```text
T0 Features
```

绝对禁止输入：

```text
未来收益
未来突破
```

输出：

```text
Shape Score 0–100
```

---

# 6.2 Model B — Outcome Model

学习：

> 什么形态未来真正容易突破。

标签来自：

```text
5D
10D
20D
```

未来真实数据。

例如：

```text
Breakout occurred
Breakout %
Breakout ATR
MFE
MAE
Hold Above Resistance
Breakout Failure
```

输出：

```text
Breakout Probability
Expected Breakout ATR
Outcome Score
```

---

# 6.3 为什么必须两个模型

例如：

```text
形态 A

Human = 5
Shape Model = 94
Outcome = Failed
```

解释：

> 这是一个“很像目标但市场结果失败”的形态。

不是：

```text
Shape Model 错了
```

可能是：

```text
我们的审美没有 Alpha
```

这正是系统应该发现的事情。

---

# 6.4 Phase 4 网页

Review 页面显示：

```text
Human Score        5
Rule Score        84
Shape Score       92
Outcome Prob      67%
```

但用户人工评分时：

```text
Outcome future result
```

仍然不可见。

---

# 6.5 Matured Cases 页面

5/10/20D 后显示：

```text
当时
vs
后来
```

例如：

```text
AMD

Human              5
Rule              88
Shape             94
Outcome Prediction 78%

20D Actual

Breakout          YES
Days to Breakout    3
Max Breakout       8.7%
Breakout ATR        4.1
MFE                10.2%
MAE                -1.8%
Failed             NO
```

---

# 6.6 四类最重要案例

系统自动生成：

## 1. Human High + Outcome High

说明：

```text
你的经验有效
```

## 2. Human High + Outcome Low

说明：

```text
你喜欢，但市场不买账
```

## 3. Human Low + Outcome High

说明：

```text
你可能漏掉有效结构
```

## 4. Model High + Outcome Low

说明：

```text
模型 False Positive
```

---

# 6.7 Learning Loop

每个训练周期：

```text
新增人工标签
+
新增 Matured Outcomes
↓
训练 Challenger
↓
Walk Forward
↓
与 Champion 比较
↓
PASS
↓
晋级
```

禁止：

```text
自动覆盖旧模型
```

---

# 6.8 Phase 4 PASS

学习模型必须：

```text
在时间外数据
```

超过：

```text
Simple Rule Benchmark
```

否则：

```text
继续使用 Rule Model
```

复杂模型不是必然更好。

---

# 7. Phase 5 — 其他优化

Phase 5 才进入高级功能。

---

# 7.1 Pairwise Ranking

网页：

```text
AMD       MU

[图]      [图]

哪一个更好？

AMD
MU
差不多
```

用来学习：

```text
相对偏好
```

比精确评分更稳定。

---

# 7.2 Active Learning

每 5 个交易日约 20 个：

```text
12 高分
4 模型最不确定
4 探索样本
```

让系统快速学习边界。

---

# 7.3 Futu Pattern Benchmark

接入富途已有形态识别结果。

页面：

```text
Our Model
vs
Futu Model
```

只做外部对照。

---

# 7.4 GitHub Pattern Benchmark

可加入：

```text
PatternPy
TradingPatternScanner
stock-pattern
chart_patterns
```

但先做 License Review。

只作为：

```text
Benchmark / Feature
```

不是 Ground Truth。

---

# 7.5 Image AI

后期才考虑：

```text
K线截图
↓
CNN / YOLO
↓
Image Shape Score
```

最终：

```text
Rule
+
OHLC ML
+
Image ML
```

做 Ensemble。

---

# 7.6 Market Context

加入：

```text
SPY Trend
QQQ Trend
Sector Trend
VIX
Relative Strength
```

然后比较：

```text
纯形态
vs
形态 + 市场环境
```

防止模型其实只是学：

```text
牛市股票会上涨
```

---

# 7.7 自动参数优化

后期才使用：

```text
Optuna
```

优化：

```text
Base Length
Base Depth
ATR Ratio
Volume Ratio
Resistance Distance
```

只能：

```text
Train + Validation
```

绝对不能优化 Test。

---

# 7.8 Pattern Battle

加入每日少量：

```text
A/B 图形对比
```

帮助 Shape Ranker。

---

# 7.9 Canonical Examples

建立：

```text
教科书好案例
典型坏案例
边界案例
```

用于：

```text
人工评分校准
```

---

# 7.10 Human Drift

定期混入旧案例。

隐藏原分数。

重新评分。

比较：

```text
Old Score vs New Score
```

判断：

```text
用户自己的标准有没有变化
```

---

# 8. 最终网页结构

阶段全部完成后：

```text
1. Dashboard
2. Today Scan
3. Review
4. Pattern Battle
5. Matured Cases
6. Before / After
7. Human vs Computer
8. Backtest Lab
9. Model Lab
10. Research Audit
```

但注意：

> 不需要第一天就做十个页面。

---

# 9. 页面建设顺序

严格按照：

## Phase 1

```text
Today Scan
Chart Review
```

---

## Phase 2

增加：

```text
Human Rating
Label History
```

---

## Phase 3

增加：

```text
Computer Score
Human vs Computer
```

---

## Phase 4

增加：

```text
Matured Cases
Before / After
Model Lab
```

---

## Phase 5

增加：

```text
Pattern Battle
Backtest Lab
Research Audit
```

---

# 10. 推荐首页最终样子

```text
------------------------------------------------
Pattern Research System
2026-08-09
------------------------------------------------

Today's Scan

Universe            4,232
Eligible            2,781
Candidates            126
Review Queue           20

------------------------------------------------

READY

Ticker  Rule  Shape  Outcome  Human

AMD      88     92      74       5
MU       85     87      69       4
PLTR     82     91      72       -

------------------------------------------------

Needs Review

[AMD chart]

Rule Score: 88
Shape Score: 92

Human:
1  2  3  4  5

[Save & Next]

------------------------------------------------

Matured Today

12 cases ready for 20D review

[Open Before / After]

------------------------------------------------
```

---

# 11. 数据库演进

## Phase 1

需要：

```text
symbols
daily_bars
scan_runs
candidates
feature_snapshots
```

---

## Phase 2

增加：

```text
human_labels
human_tags
```

---

## Phase 3

增加：

```text
rule_versions
rule_scores
```

---

## Phase 4

增加：

```text
future_outcomes
model_versions
model_predictions
training_runs
```

---

## Phase 5

增加：

```text
pairwise_labels
experiments
backtest_runs
audit_events
```

---

# 12. 每个阶段的 Stop / Go Gate

这是整个产品最重要的管理规则。

---

# Phase 1 Gate

先检查运行频率：

```text
是否能够稳定按每 5 个交易日生成一个新的 Scan Batch？
是否在扫描前把 OHLCV 更新到最新交易日？
是否避免重复生成同一 T0 批次？
```

然后问：

```text
系统找出来的图，我愿不愿意人工看？
```

如果：

```text
NO
```

继续优化 Scanner。

不做评分系统。

---

# Phase 2 Gate

问：

```text
人工评分是否稳定并且有足够数据？
```

如果：

```text
NO
```

继续收集标签。

不训练 ML。

---

# Phase 3 Gate

问：

```text
透明规则评分是否能大致表达我的标准？
```

如果：

```text
NO
```

继续调整 Feature / Rule。

不急着 ML。

---

# Phase 4 Gate

问：

```text
机器学习在未见数据有没有超过简单规则？
```

如果：

```text
NO
```

不晋级。

Rule Model 保持 Champion。

---

# Phase 5 Gate

任何新高级功能必须回答：

```text
它有没有带来可验证提升？
```

如果没有：

```text
删除 / 不使用
```

---

# 13. 每阶段独立可用价值

这点很重要。

即使项目停在：

## Phase 1

你已经有：

```text
自动全市场找形态网页
```

有价值。

---

即使停在：

## Phase 2

你已经有：

```text
形态数据库
+
人工标签
+
未来结果记录
```

很有价值。

---

即使停在：

## Phase 3

你已经有：

```text
透明电脑评分
+
每 5 个交易日自动排名
```

可以直接使用。

---

只有当 Phase 4 确实更好：

才使用 ML。

---

# 14. 最小产品路线

真正开发时建议：

# MVP-1

只实现：

```text
Futu数据
全市场扫描
Flat / Rounded
网页K线
```

确认：

```text
它找得到对的图
```

---

# MVP-2

增加：

```text
1–5人工评分
Tags
Snapshot
```

确认：

```text
标签可长期使用
```

---

# MVP-3

增加：

```text
Rule Score
Human vs Computer
```

确认：

```text
电脑大致理解规则
```

---

# MVP-4

增加：

```text
5/10/20D
Before / After
Shape ML
Outcome ML
```

确认：

```text
机器学习真正有价值
```

---

# MVP-5

增加：

```text
Active Learning
Pairwise
Futu Benchmark
GitHub Benchmark
Optuna
Image Model
Regime
Audit
```

---

# 15. 最终研发原则

整个项目不追求：

```text
一开始功能最多
```

而追求：

```text
每增加一层智能
都能够证明：
这层没有把系统搞坏
```

系统发展逻辑：

```text
能找图
↓
能记录人的判断
↓
电脑能解释性评分
↓
电脑能学习人的判断
↓
电脑能学习真实市场结果
↓
再考虑高级 AI
```

这比：

```text
先做一个很复杂的 AI 系统
再希望它有效
```

可靠得多。

---

# 16. ChatGPT / Codex 分工

## ChatGPT

负责：

```text
产品逻辑
研究设计
Shape定义
评分逻辑
Outcome定义
防偏差
模型评价
Phase Gate
结果解释
```

---

## Codex

每一个阶段只负责：

```text
读取当前仓库
↓
为当前 Phase 写 Implementation Plan
↓
实现
↓
测试
↓
展示可运行网页
↓
停止
```

直到用户和 ChatGPT共同确认：

```text
PHASE PASS
```

才允许开始下一阶段。

---

# 17. Codex 实施纪律

每一次只给 Codex 一个 Phase。

例如第一次：

```text
只实现 Phase 1
```

明确禁止：

```text
不要加入 Human Rating
不要加入 ML
不要加入 Future Outcome
不要加入 Optuna
不要加入 Image AI
```

避免 Codex 自己“顺便多做”。

---

# 18. 推荐项目目录演进

```text
tv_quant_system/
│
├── src/
│   ├── data/
│   │
│   ├── universe/
│   │
│   ├── patterns/
│   │
│   ├── features/
│   │
│   ├── scoring/
│   │
│   ├── outcomes/
│   │
│   └── models/
│
├── app/
│   ├── Home.py
│   └── pages/
│
├── data/
│
├── models/
│
├── tests/
│
└── docs/
    └── superpowers/
        ├── specs/
        └── plans/
```

但实际实现前：

> Codex 必须先读取现有仓库结构。

不能因为蓝图这样写就强行重构已有项目。

---

# 19. 最重要的五个产品问题

整个系统未来始终围绕以下五个问题：

## Q1

```text
系统找出来的图像不像我要的？
```

Phase 1。

## Q2

```text
我自己到底喜欢什么？
```

Phase 2。

## Q3

```text
电脑能不能理解我的规则？
```

Phase 3。

## Q4

```text
电脑能不能学得比人工规则更好？
```

Phase 4。

## Q5

```text
这些漂亮形态到底有没有真实市场价值？
```

Phase 4–5。

---

# 20. 产品成功标准

最终系统成功不是：

```text
AI分数越来越高
```

也不是：

```text
网页越来越复杂
```

而是：

### 1
每 5 个交易日能快速找出值得看的候选。

### 2
电脑推荐越来越接近用户真正认可的形态。

### 3
系统知道自己的推荐后来是否有效。

### 4
能发现：

```text
用户看对而模型看错
模型看对而用户看错
两边都错
```

### 5
新模型只有在真正未见数据上更好才晋级。

### 6
系统始终可以回到：

```text
当时看到了什么
当时为什么打这个分
后来发生了什么
模型为什么改变
```

---

# 21. 下一步

## 21.1 V2.1 时间口径已经锁定

开发时不得混淆：

```text
SCAN_INTERVAL = 5 Trading Days

OUTCOME_WINDOWS = [5, 10, 20] Trading Days
```

两者必须分别配置、分别测试。

本蓝图批准后，不直接开发完整系统。

第一步只做：

# Phase 1 — Pattern Finder

Codex 下一份文档应该是：

```text
Phase 1 Implementation Plan
```

范围只允许：

```text
股票池
Futu日线数据
本地缓存
Flat Base
Rounded Base
Compression
Candidate Scanner
Today Scan页面
Chart Review页面
基础测试
```

验收后：

```text
PHASE_1_PASS
```

才开始 Phase 2。

---

## END
