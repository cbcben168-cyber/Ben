# C1 Phase 3 Edge Research Engine

Run from the repository root:

```powershell
python run_research.py
```

The command validates the frozen 19,470-bar SPY 5-minute cache and the complete `opend_rehab.csv` identity, computes the frozen 36-factor registry, independently replays S01-S03 and six pre-registered filter variants, and creates `outputs/phase3_train_v3/`. The frozen `phase3_train_v1/` and `phase3_train_v2/` directories are protected from writes, and the command refuses to overwrite an existing V3 directory.

V2 defines the estimand as the equally weighted trade/event mean. Each bootstrap draw resamples whole trading days and recomputes that same estimand. All hypotheses in a family share one calendar-day index draw; missing events remain zero-count clusters, and untestable pre-registered hypotheses remain in the Holm family size.

V3 preserves that estimator and multiplicity algorithm while making factor baselines direction-consistent. `baseline_raw_market` is the unconditional TRAIN market return for the horizon. `baseline_directional` equals that return for Long and its negative for Short; it is not applicable to Regime rows. The compatibility field `baseline_mean` is the actual comparison baseline used by `increment`. `INFERENCE_TARGET = DIRECTIONAL_MEAN_VS_ZERO`: existing confidence intervals and p-values test the directional mean against zero, not increment against its baseline.

`STATISTICS_PASS` is computed only from the machine-readable `STATISTICS_GATE.json`. The Gate checks registry and family completeness, baseline/increment identities, count and sample-status legality, finite estimable statistics, p-value/Holm ordering, simultaneous-interval containment, candidate rules, V2→V3 permitted differences, and unchanged V1/V2 hashes. A failed Gate blocks candidate promotion and makes the CLI return a non-zero exit code; a valid `RESEARCH_NO_EDGE` remains a successful engineering outcome.

The default run also reads the frozen real V3.1.1 RunLog from Downloads and performs one-to-one signal, decision, rejection, and trade parity. It fails closed as `PARITY_FAIL` if the file identity or any comparison fails. Raw as-of-basis prices are converted with the four frozen forward-adjustment coefficients before applying the absolute `1e-9` price tolerance; return tolerance is `1e-12`.

To add a factor, add one frozen row to `registry/FACTOR_REGISTRY.csv`, add the matching deterministic column in `compute_factor_matrix()`, and add a formula test. Do not change an existing row after results have been observed; create a new attempt version instead.

The engine is offline and price-only. It does not use Volume/VWAP, account, position, order, Validation, or OOS data. A 5-minute stop/target collision is recorded as path-uncertain and uses stop-first for the primary result.
