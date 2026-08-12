# K线形态研究系统：全市场扫描与开放式人工复核产品蓝图 V3

**版本**：V3

**日期**：2026-08-11

**项目**：K线形态研究系统 / Pattern Research System

**状态**：产品设计冻结稿

**适用阶段**：Pattern Research System / Phase 1 后续规模化设计

---

## 1. 这份蓝图解决什么问题

本蓝图解决三个规模化问题：

1. 美国市场证券数量接近万级，不可能所有证券无差别进入研究系统。
2. 即使基础筛选后仍可能有上千只股票，必须让机器在短时间内批量完成扫描。
3. Detector 筛选后仍可能产生大量候选，人工复核必须做成高效率、可中断、可继续、没有每日硬数量上限的工作流。

核心原则：

> **机器承担规模，人负责判断。**

用户每天能看多少就看多少。系统负责排序、去重、保存 Backlog、保存人工进度和下次继续。

---

## 2. 四层 Funnel 总体架构

```text
美国市场全部证券
        ↓
Universe Funnel
        ↓
Research Universe
        ↓
Compute Funnel
        ↓
Detector Results
        ↓
Pattern Funnel
        ↓
Review Backlog
        ↓
Human Funnel
```

人工不处理整个 Universe，只处理 Review Backlog。

---

## 3. 默认 Universe：CORE v1

当前冻结默认设置：

```text
Market:
- NYSE
- NASDAQ
- AMEX

Security Type:
- Common Stock only

Price:
- >= $5

Market Cap:
- >= $1B

20D Average Dollar Volume:
- >= $20M

Listing History:
- >= 250 Trading Days

Sector:
- ALL

ETF:
- OFF
ADR:
- OFF
OTC:
- OFF
Preferred:
- OFF
Warrant:
- OFF
Unit:
- OFF
Inactive / Delisted:
- OFF
```

目标是先建立流动性足够、可交易性较高、噪声相对较少的核心研究股票池。

---

## 4. Universe 设置必须可调整

CORE v1 是默认配置，不是永久写死规则。

系统后续必须允许调整：

- 市场 / Exchange
- 最低/最高股价
- 最低/最高市值
- 最低 20D 平均成交额
- 最低平均成交量
- 最低上市历史
- Sector
- Industry
- ETF / ADR 等证券类型开关

未来允许创建：

```text
CORE
LARGE_CAP
MID_CAP
SMALL_CAP_RESEARCH
TECH_ONLY
SEMICONDUCTOR
CUSTOM_xxx
```

---

## 5. Universe 必须版本化

不能直接修改旧 Universe 条件并覆盖历史。

例如：

```text
CORE v1
Market Cap >= $1B
```

未来调整为：

```text
CORE v2
Market Cap >= $500M
```

历史 scan batch 仍必须保留原版本。

每个版本至少保存：创建时间、完整过滤条件、版本说明、实际通过股票数量、scan_batch_id。

---

## 6. Universe Funnel 可视化

系统应展示真实漏斗：

```text
美国证券总数
↓
普通活跃股票
↓
交易所符合
↓
价格符合
↓
市值符合
↓
流动性符合
↓
历史长度符合
↓
CORE Universe
```

每一级必须使用实际计算值，不能写死。

---

## 7. Sector / Industry

Sector 默认 ALL，不建议默认只做科技股，以防 Sector Bias。

系统必须记录：Exchange、Sector、Industry、Market Cap、Market Cap Bucket。

Universe 条件与 Detector 数学逻辑必须分离。

---

## 8. 正式扫描节奏

继续采用：

```text
SCAN_INTERVAL_TRADING_DAYS = 5
```

表示每隔 5 个交易日创建一次新 Scan Batch。

---

## 9. Cold Start 与 Warm Cache 分开

第一次建立几千只股票的数据基础时，采用 quota-aware Universe Hydration，逐批完成历史数据下载。

一旦股票已有历史数据，后续只补新交易日，禁止每 5 个交易日重新下载完整历史。

---

## 10. 数据层双层设计

### Layer A — Canonical Raw Cache

职责：Futu QFQ 日线事实、Data Quality、provenance、可回放。

### Layer B — Scan Read Model

为几千只股票批量计算建立高性能只读层。候选技术：Parquet、DuckDB、PyArrow；最终由 benchmark 决定。

---

## 11. Compute Funnel

正确流程：

```text
批量读取
↓
共享特征预计算
↓
Detector 批量运行
↓
一次性保存 Scan Snapshot
```

避免逐只反复开小 CSV、重复计算公共指标、重复访问网络。

---

## 12. Stage 0 — Data Eligibility

全部股票先检查 Data Quality、历史长度、stale、missing sessions、symbol identity、OHLC 合法性。

只有 DATA QUALITY = PASS 才允许进入 Detector。

---

## 13. Stage 1 — Shared Feature Precompute

同一个 scan batch 内，公共特征只算一次，例如 ATR14、20D/60D Volume、Rolling High/Low、Range、Linear Regression 基础量、Pivot 辅助数据、120D Range Position。

---

## 14. 性能预筛不能偷偷降低 Recall

Phase 1 继续以 High Recall 为目标。

任何新增 Cheap Gate 若会排除原本可进入 Detector 的股票，必须独立版本化、做 recall audit，并用已知正样本证明不会明显漏掉目标形态，才允许成为 hard gate。

---

## 15. Stage 2 — Pattern Detectors

当前：Flat Base / phase1-v1。

未来：Rounded Base、Compression、READY 等。

Detector 必须独立、透明、可版本化。市值、板块等 Universe 信息不能偷偷混入形态数学判断。

---

## 16. 每次扫描保存全部 Machine Results

至少保存：scan_batch_id、scan_date、universe_profile_id/version、symbol、exchange、sector、industry、market_cap、pattern_type、detector_version、computer_result、diagnostics、data_quality。

Computer = NO 也必须保存。

---

## 17. Pattern Instance 与去重

同一个股票的同一个底不应每 5 个交易日制造一个新人工任务。

建立 pattern_instance_id。

建议状态：NEW、CONTINUING、MATERIAL_CHANGE、REVIEWED、SNOOZED、ARCHIVED。

Scan Snapshot 全部保留，但人工默认只处理新实例、重要变化、NO→YES、YES→NO、窗口明显变化或用户主动重审。

---

## 18. Open Review Queue：人工不设每日数量上限

正式取消：每天20张、每批20张、12+4+4固定数量。

采用 Open Review Queue：

- 队列可以任意长度；
- 用户今天看 3 张也可以，看 80 张也可以；
- 没看完不会丢；
- 下次继续；
- 新 Scan Batch 可与旧 Backlog 合并；
- 未看完不能阻止下一批机器扫描。

---

## 19. Priority Queue：开放数量不等于无排序

优先级建议：

A. NEW DETECTOR YES
B. MATERIAL CHANGE
C. BORDERLINE NO
D. EXPLORATION

不规定每类必须看多少，只显示 Coverage Awareness。长期完全不看 Exploration 时可以提示选择偏差风险，但不得强制。

---

## 20. Review Backlog

扫描后形成长期 Backlog，显示待复核总数、新形态、变化案例、Borderline、Exploration。

用户看多少就记录多少，剩余下次继续。

---

## 21. 新 Scan Batch 与旧 Backlog 合并

```text
旧未复核
+
新 Scan Batch
↓
Pattern Instance Dedup
↓
Priority Reorder
↓
新的 Open Review Queue
```

旧案例不丢失，也不要求先全部完成。

---

## 22. UI 页面结构

未来建议：

- 首页 / 扫描控制台
- 股票池设置
- 候选画廊
- 极速复核
- 历史复核
- 研究统计

按 Milestone 分阶段实现。

---

## 23. 扫描控制台

显示最近扫描、Universe Profile、研究股票池数量、Data PASS、每种 Pattern 的 YES/Borderline、Review Backlog。

按钮：更新行情、运行扫描、继续复核、查看全部结果。

---

## 24. 候选画廊

一次展示多张小型 K 线卡片，显示股票、形态、Computer 结果、Sector、Cap Bucket、NEW/变化状态。

支持按 Pattern、Computer YES/NO、Priority、Sector、Cap Bucket、人工标签、Validation Result、Scan Batch 筛选。

---

## 25. 极速复核模式

主要人工页面：大 K 线 + 识别区间/支撑/阻力 + Computer 结果 + Diagnostics + 人工像/勉强像/不像 + 当前形态专属原因标签 + 备注。

必须支持：保存并下一张、上一张、跳过、稍后再看。

建议未来支持：1=像、2=勉强像、3=不像、S=跳过、左右箭头切换。若 Streamlit 不稳定，先做按钮版本。

---

## 26. Review 页面性能

切换下一张不能重连 Futu、重新下载行情、重跑整个 Universe 或所有 Detector。

只读取 Scan Snapshot + 本地K线 + 人工历史，目标是接近即时切换。

---

## 27. Computer YES / NO 解释

YES：显示正式识别区间、支撑位、阻力位，并明确 Detector 正式识别成功。

NO：如有最佳候选窗口，显示“最佳候选复核区间（未通过）”、候选支撑/阻力，并明确仅用于解释判 NO，不代表正式识别。

Flat Base NO 还必须显示硬条件的实际值、冻结阈值与 PASS/FAIL，不用黑箱0–100分数替代。

---

## 28. Historical T0

历史研究仍按每 5 个交易日一个 T0：机器批量扫描 → Pattern Instance → Dedup → Review Backlog → 用户想看多少看多少。

不能把所有历史 T0 直接要求人工查看。

---

## 29. Anti-Lookahead

历史 T0：Detector 输入和 Review Chart 都只能包含 Date <= T0。

禁止 T0 后K线、Future Outcome、未来突破和后续收益。

任何 future bar 泄漏都是 BLOCKER。

---

## 30. Survivorship Bias

如果历史回放使用今天仍存在的股票池，必须标识 CURRENT-UNIVERSE REPLAY，不能称为 FULL HISTORICAL MARKET BACKTEST。

未来若获得 historical security master + delisted universe，再建立严格历史 Universe。

---

## 31. 性能与 Benchmark

优化顺序：Universe 缩小 → Warm Cache → 增量更新 → Batch Read → Shared Feature Precompute → Detector 批量运行 → Pattern Instance Dedup → Review 不重跑市场。

优先 Windows 单机方案。

至少 benchmark：500、1000、2000、3000 symbols。

记录数据读取时间、共享特征时间、Flat Base Detector 时间、总耗时、Peak Memory。

当前目标是分钟级而不是小时级，正式 SLA 在 benchmark 后冻结。

---

## 32. 人工复核没有完成率目标

可以显示已复核、未复核、队列位置，但默认不能出现“今日目标20”“完成率60%”。

退出后保存 Review Queue、当前位置、未完成案例和人工记录，下次支持“继续上次复核”。

---

## 33. 防 Selection Bias / Confirmation Bias

必须保存所有 Machine Results、被看/未看/跳过/稍后再看的案例。

Exploration 必须存在，但不规定用户每批必须看多少。

人工页面展示 Computer YES/NO、diagnostics 和 review reason，避免“精品、高胜率、强烈推荐”等暗示性语言。

---

## 34. Review Reason

每个进入人工队列的案例记录：NEW_DETECTOR_YES、MATERIAL_CHANGE、BORDERLINE、EXPLORATION、USER_REQUESTED。

---

## 35. 多形态 Review 单元

同一股票可能同时 Flat Base、Rounded Base、Compression。Review Key 应为 symbol + pattern_type + pattern_instance，不能合并成“股票只复核一次”。

---

## 36. 给 ChatGPT 的研究摘要

支持导出：pattern_type、detector_version、universe_profile、scan_batch、sample_count、computer YES/NO、human 像/勉强像/不像、一致命中/排除、疑似误报/漏报、边界案例、top reason tags。

并自动挑选典型正确、明显误报、明显漏报、边界、接近阈值案例。

---

## 37. 推荐实施顺序

M3C-A Universe Foundation：Universe Profile Schema、CORE v1、可调整参数、版本化、Universe Funnel、Universe Snapshot。

M3C-B Scale Data & Compute：quota-aware hydration、warm-cache incremental、Scan Read Model、batch compute、benchmark。

M3C-C Pattern Instance & Dedup：pattern_instance_id、NEW/CONTINUING/MATERIAL_CHANGE、Review Backlog。

M3C-D Review UX：Candidate Gallery、Open Review Queue、Continue Review、Save & Next、Skip/Snooze、可选快捷键。

M3C-E Historical T0：5-session T0、anti-lookahead、current-universe replay warning、historical Review Backlog。

每个阶段独立 Gate。

---

## 38. Gate 标准

M3C-A：CORE v1正确、参数可调、Profile版本不可篡改、Universe Funnel真实、Snapshot可追溯。

M3C-B：Cold Start 遵守 quota、Warm Cache 只增量、500/1000/2000/3000 benchmark 完成、Batch Detector 与单只一致。

M3C-C：同一延续 Pattern 不反复制造人工任务、Scan Snapshot 全保留、NEW/CHANGE/BORDERLINE/EXPLORATION 可区分。

M3C-D：人工没有每日上限、Backlog 不丢、保存后快速下一张、退出后可继续、Pattern-specific reasons 正确。

M3C-E：T0 后 bar 不进入 Detector/Review、Replay 标识准确、没有 Survivorship Bias 误导表述。

---

## 39. 当前冻结决策

Universe：CORE v1 = NYSE/NASDAQ/AMEX、Common Stock only、Price >= $5、Market Cap >= $1B、20D Average Dollar Volume >= $20M、Listing History >= 250 Trading Days、Sector = ALL，ETF/ADR/OTC/Preferred/Warrant/Unit = OFF。

Universe 设置未来必须可调，并且所有正式修改创建新版本。

Scan：每 5 个交易日。

Human Review：Open Review Queue / No Daily Hard Limit。

> 用户每天能看多少就看多少。

---

## 40. 下一步

本蓝图批准后：

1. 保存为 GitHub 权威 Spec；
2. 同步一份 Obsidian Markdown；
3. 只为 M3C-A Universe Foundation 写 Implementation Plan；
4. 不一次性开发 M3C-A～E；
5. M3C-A 人工验收 PASS 后才进入 M3C-B。

> 下一步不是写全系统，而是先把 Universe Foundation 做正确。
