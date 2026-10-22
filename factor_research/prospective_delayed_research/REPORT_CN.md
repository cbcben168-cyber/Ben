**MF038/MF043 A2 工程实施与验收报告**

日期：2026-10-23，Asia/Shanghai（客户端日期）。结论：**A2_SYNTHETIC_ENGINEERING_PASS**，实际前瞻采集尚未启动，独立样本计数为 0。

**实施计划**

- [x] 先新增 Synthetic 测试；实现文件不存在时测试收集按预期失败。
- [x] 原样保留 A 基线的数学函数，新增输入前缀、逐事件持久化、参考预热和失败关闭逻辑。
- [x] 验证未来扰动不改变已封存预测，验证双阶段 fsync、迟到、缺失、修订、重启和时间边界。
- [x] 冻结工程合同的代码和基线身份；最终相关 pytest 64 项通过。
- [x] 独立目录四文件测试 39 项通过；仅四文件功能分支交付。

**授权边界**

本批准仅含四个新文件、Synthetic 工程验证与独立 Draft PR。真实 OpenD 连接、自动调度、正式研究 Run、Phase 4、交易和 PR 合并未获批准。

**接口**

`Collector(path, clock)` 创建一次性 Synthetic 证据目录；`ingest(payload)` 保存原始响应并验证完成 K 线；`mature_reference(anchor, horizon)` 封存已成熟参考；`predict_event(factor, anchor, horizon)` 只读取截止前缀并封存预测；`collect_label(prediction_id, fetch)` 在预测封存及目标成熟后才调用标签源；`verify_bundle(path)` 复核 Manifest、事件链和持久化回执。

工程版本不提供真实 OpenD、调度或评分入口。Synthetic 时间证明始终标为模拟，不能成为真实前瞻资格。

**最小新增范围与基线身份**

仅新增本目录四个文件：`RESEARCH_CONTRACT.json`、`collector.py`、`test_collector.py`、`REPORT_CN.md`。不导入旧研究模块。

A 基线为 Attempt 02，仍仅是 `HISTORICAL_REPLAY_ENGINEERING_PASS`：

- A collector SHA256：`dafebdd417d133761b4bc072264a28936d6469f212a16cd02796bb0f47a5902e`。
- A contract SHA256：`eea86e04d5edc04d28612721627b0a69c1a476fc9919a04685ffed69b5554ac8`。
- Attempt 02 Manifest：`ea382b92ad4b927f0d282d97e2dfc1e0d378604339e8f8a263d4c4b35300e464`。
- 新合同 SHA256：`ddde98cb60c363ff5817f4b691778a65f5725380a8ec93525bd17ce8a5d27843`。
- 新 collector SHA256：`fa613cd9c9a77abbc64ff8f112767802636f9131213f88908991b58ace8bd62a`。
- 新 test_collector SHA256：`0ca65c0f3ad1fcaea5b51ce9b1b5af7f313a5c1afcd95b6aff18628b62eff3ef`。

`rearm/signals/predict/target` 四个数学函数与 A 基线 AST 完全一致，并在新合同中固定各自 AST SHA256；孤立运行时仍验证这些摘要。没有重筛 2019–2024、重放历史数据或修改任何因子公式。

**合同冻结的含义与条件**

工程合同状态为 `ENGINEERING_FROZEN`，记录时间 `2026-10-22T17:42:43Z`（北京时间 2026-10-23 01:42:43）。该 UTC 记录未经真实时钟资格验证，合同明确保留 `LOCAL_UTC_UNQUALIFIED_REAL_COLLECTION_REQUIRES_SEPARATE_PROOF`。它用于此次 Synthetic 工程边界，不能单凭该字段证明真实样本起点。

合同固定代码身份、运行库版本、原数学规则、延迟目标、失败政策和执行授权。运行库为 numpy 2.5.1、pandas 3.0.3、exchange-calendars 4.13.2、tzdata 2026.3；漂移时拒绝执行。真实 OpenD、调度、正式研究 Run、Phase 4 和交易授权全部为 false。

正式真实采集前，仍需单独批准并封存真实采集合同与可验证冻结时间/起点。只有冻结且预检通过后的首个完整 XNYS Session 及以后数据可进入新队列；预热也从冻结后新交易日积累，旧缓存不补入。此次工程冻结不改写旧 Phase 3 草案，不启动或宣称正式 Phase 4。

**收集顺序与 SHA256 身份**

1. 独占创建新证据目录，记录合同、代码、依赖版本和唯一进程身份；已有目录拒绝，不自动恢复或重试。
2. 保存原始响应的原文 JSON、SHA256、观察时钟和 fsync 回执。无效价格等异常原文也保留；通过检查后另写 `RAW_ADMITTED`，避免把失败响应当成已接纳输入。
3. 按 XNYS 的 5 分钟 RTH 完成网格、UTC 时间、实际观察、版本、公司行动和 regime 检查。未知完成证明、形成中、乱序、重复、缺失、价格异常或迟到均失败关闭。
4. 预测只读取锚点以前输入。MF038 使用精确 prior-20 合格同钟点同 regime 参考；MF043 在前 60 个 Session 中至少有 40 个有效成熟同钟点同 regime 参考，缺失 Session 保持窗口位置，blackout 参考按原规则处理。
5. 预测事件 fsync，独立回执再 fsync；随后写入 `PREDICTION_READY` 及其回执。两个封存阶段均必须严格早于目标开始，不能用 READY 的时间掩盖较早阶段迟到。时钟资格丢失或 UTC 回拨保持 sticky 失败。
6. 目标成熟后封存 `LABEL_REQUEST`，确认其完成回执和资格，才调用注入的 Synthetic 标签源；取得目标完成 K 线后封存标签及独立完成回执。标签处理期间失去资格也保留失败；如标签已经写入则追加失效记录。
7. 写入 `END` 与 Manifest。独立验证器复核文件大小/SHA256、事件/回执链、进程顺序、关联身份、精确参考成员、输入截止、截止/目标成熟时间、标签数学计算以及失效后的有效计数。

每个输入/参考/预测/标签均有内容身份，逐事件链和独立回执互相关联。预测摘要只绑定当时的输入版本，不绑定日后增长的整日文件。标签目标 K 线后续修订也会追加 `INVALIDATION`；旧预测/标签保持不变，有效计数排除失效记录。

本版本使用外部注入的 Synthetic 行情与时钟，未实现可执行的真实 OpenD 适配器。未来真实适配器必须是 quote-only，经过单独授权及资格验收；工程版本拒绝 `OPEND` 来源，不包含账户、订单、NTP 或调度代码。

**独立前瞻资格标准**

新交易日并不自动取得资格。真实样本还必须证明输入已经完成且在封存前实际取得、参考当时可用并已成熟、预测及回执早于目标开始、标签后取得以及完整版本/公司行动身份。跨进程 monotonic 数值不能用来证明跨重启顺序；本版本直接拒绝恢复已有 Attempt。

MF038 保持 10:00 ET 锚点、严格早于 10:05 完成封存；一根缓冲 K 线后，h=6 目标为 10:05–10:35 区间（目标 K 线结束标记为 10:10 至 10:35）。MF043 对每个事件保持同样的原始缓冲与目标规则。h=3/12 仅为原定补充目标。

收盘后才封存当日预测，即使此后才读取标签，也不能证明早于目标开始；必须失败，不能计入合格前瞻样本，也不能自动后移目标。真实截止证据未知时保持 `NOT_VERIFIED`，不能把历史收盘 K 线解释为 10:05 前实时可用。

所有本次输出都标记 `SYNTHETIC_ENGINEERING_ONLY` 和 `prospective_eligible=false`，独立验证器的真实前瞻合格计数固定为 0。`simulation_temporal_eligible` 只描述模拟顺序，并受到失效记录约束。

**实际验证结果**

最终相关测试：**64 passed in 132.58s**，其中 A2 39 项、原 A 收集器 25 项。未运行全仓库测试；仅新增独立模块，旧模块字节未改。

覆盖数学 AST parity、prior-20/60 与最少 40、MF043 实际事件、未来价格扰动/前缀一致性、缓冲、DST/提前收盘、公司行动/重建、NaN/乱序/缺失/形成中数据、双阶段 fsync、迟到和 UTC 回拨、标签源失败与禁止重试、标签期间时钟丢失、输入/参考/目标修订、断写/已消耗目录、篡改、有效哈希但错误关联的语义证据。

实现前红灯为缺少 collector.py 的收集错误；后续开发中先后完成 19、29、33、38 项阶段回归，最终增加嵌套失败回归后达到 39 项。中途一次为缩减与数学依赖无关的重复参考材料处理而主动中断，不是完成的通过运行。最终结论只引用最终完整 64 项结果。

独立只读代码审查发现的目标修订、UTC 回拨、语义验证、失败重建和标签期间时钟丢失等问题均已修复并加入回归；最后一次聚焦审查未发现遗留 finding。审查代理未独立执行测试，测试结果来自上述实际 pytest。

仅包含四个交付文件的独立临时目录测试：**39 passed in 128.19s**，退出码 0。该目录无 A 收集器或其他旧研究模块；固定 AST 摘要校验仍执行。报告收尾后同步最终报告，另比较四个文件的字节摘要，未因报告更新而重复运行不受影响的测试。

**命令与输出**

使用既有 `C:/Users/cbcbe/AppData/Local/Programs/Python/Python314/python.exe`，没有安装依赖。最终测试命令：

```powershell
& 'C:/Users/cbcbe/AppData/Local/Programs/Python/Python314/python.exe' -B -m pytest factor_research/prospective_delayed_research/test_collector.py factor_research/delayed_bar_research/test_collector.py -q -p no:cacheprovider --import-mode=importlib
& 'C:/Users/cbcbe/AppData/Local/Programs/Python/Python314/python.exe' -B factor_research/prospective_delayed_research/collector.py verify-contract
```

另执行了只读 Git/源码/Manifest 核验、SHA256 和 AST 检查、`git fetch origin codex/forward-factor-signal-design`，以及独立暂存区的 `read-tree/add/diff --cached --check/write-tree/commit-tree/update-ref` 与明确功能分支推送。只创建独立 Draft PR，不改 PR #35。

项目中只新增四个交付文件，没有生成真实采集 Run。Synthetic 的 `EVENTS.jsonl`、`RECEIPTS.jsonl`、`MANIFEST.json` 都位于 pytest 临时目录；正反测试中故意损坏的证据不得当作合格输出。

**受保护对象与 Git 方案**

执行前后核验：factor_batch_screen 整树 123 个文件摘要 `6d43bc30f3fd391cb19fb439caf32661b37bfcd1b51b9f30cbb1771f7aef7f25`；delayed_bar_research 整树 24 个文件摘要 `68bfac6625c9d21af1cea9ec94a70c67ad3a14b9fb7c5ed30aecd740902384bf`。算法为按路径排序的相对路径/文件 SHA256 列表的规范 JSON 摘要，排除 __pycache__。两个摘要均未改变，含旧合同、旧 Run 和 Prepared 所在保护树。

当前 checkout 仍为 `codex/phase3-ntp-reliability`，HEAD `3f7c309e6dfa5625b8e82b4e3322fc49cd0c1264`；原暂存区 SHA256 `bc965f3f769920009b2665928052ef8f7c4a8fb1023678f44a1a730825e4ef69` 与原 tracked diff 摘要均未变。未暂存、覆盖或清理其他用户文件。

新增分支 `codex/mf038-mf043-a2-prospective-delayed-research` 从同步后的远端默认分支 `codex/forward-factor-signal-design` 的 `5eefc7bdb229b8766a3fefcbc5f4113bf04f95cb` 构建。使用独立 Git index，只提交四个新增文件，保留当前 checkout。PR #35 保持 Draft、未合并。

**首次真实采集与 Phase 4 尚缺的 Gate**

首次真实采集需要单独授权具体标的、窗口、接口、停止/重试政策和输出身份；还需实现并审查 quote-only 适配器、封存真实合同与起点、证明真实完成 K 线和到达时间语义、公司行动的当时可用版本、预测封存顺序与绝对截止、机器与日志完整性。无需从本工程版本自动推导 Clock V3 状态或执行维护/校时。自动调度仍需另一项授权。

Phase 4 尚缺独立正式合同和执行授权、真实数据资格、冻结后独立预热，以及 MF038 至少 300 配对 Session；MF043 至少 300 事件/100 Session、两个方向各至少 100 事件。共同盲终点、24 个月或 504 个计划 Session 的较早上限、只按计数停止、Holm 两假设族与 blocked p=1、Session 推断和稳定性规则还需正式冻结及执行。此次不计算正式聚合效应、不解盲或启动这些流程。

届时仍须通过 MAE/RMSE、增量 skill/置信区间、显著性和稳定性等原定预测能力 Gate。达到样本门槛不等于效果通过；预测能力通过也不代表扣除成本后的交易盈利。

**限制**

工程合同固定当前依赖版本及源码字节（包括 LF 换行）；自动转换换行也会触发身份失败，使用时需保留获验字节。版本更新必须重新审查。此模块为顺序单进程接口；断写、已有目录、历史输入缺口和时钟丢失均保守失败，不提供自动恢复、追补或重试。Synthetic 无法证明 OpenD 的真实延迟、完成性、时钟或公司行动 PIT。它不构成 OOS、Forward 或 Trading Edge PASS，也不启动正式 Phase 4。
