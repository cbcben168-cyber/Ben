# C1 Phase 3 V2→V3 统计完整性修复差异报告

## 结论

- 差异 Gate：`PASS`。
- 冻结研究对象不变：36个因子、9个策略版本、同一TRAIN、同一信号与交易规则。
- 因子检验行：192；Short 行：78。
- `baseline_mean` 允许变化行：78；`increment` 允许变化行：78。
- 新增字段完整：`true`。
- 非预期因子变化：0；非预期策略变化：0。
- TRAIN_CANDIDATE：0→0。

## 九个策略版本（ALL方向）

- S01_BASE：交易 808→808；平均净收益 -4.0000→-4.0000bp；PF 0.4825→0.4825；候选 NO_EVIDENCE→NO_EVIDENCE。
- S01_F015：交易 9→9；平均净收益 -1.1429→-1.1429bp；PF 0.9113→0.9113；候选 NO_EVIDENCE→NO_EVIDENCE。
- S01_F036：交易 598→598；平均净收益 -4.1466→-4.1466bp；PF 0.4832→0.4832；候选 NO_EVIDENCE→NO_EVIDENCE。
- S02_BASE：交易 183→183；平均净收益 -0.6545→-0.6545bp；PF 0.9333→0.9333；候选 NO_EVIDENCE→NO_EVIDENCE。
- S02_F023：交易 24→24；平均净收益 +3.5521→+3.5521bp；PF 1.4292→1.4292；候选 NO_EVIDENCE→NO_EVIDENCE。
- S02_F029：交易 19→19；平均净收益 +5.5576→+5.5576bp；PF 1.8442→1.8442；候选 NO_EVIDENCE→NO_EVIDENCE。
- S03_BASE：交易 81→81；平均净收益 -4.0432→-4.0432bp；PF 0.5601→0.5601；候选 NO_EVIDENCE→NO_EVIDENCE。
- S03_F021：交易 9→9；平均净收益 -7.7254→-7.7254bp；PF 0.1885→0.1885；候选 NO_EVIDENCE→NO_EVIDENCE。
- S03_F034：交易 58→58；平均净收益 -4.4789→-4.4789bp；PF 0.5459→0.5459；候选 NO_EVIDENCE→NO_EVIDENCE。

## 统计解释

- V3 将 Short 的比较基准方向化；REGIME 继续对比原始无条件市场收益。
- `INFERENCE_TARGET = DIRECTIONAL_MEAN_VS_ZERO`；现有 CI/p-value 不解释为 increment 显著性。
- 只有 Short baseline/increment、新字段、Gate证据、版本哈希和运行耗时允许变化。
- 任一信号、交易、净收益、PF、方向均值、rank、CI/p-value或候选变化均阻断验收。
