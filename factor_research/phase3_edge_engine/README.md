# C1 Phase 3 Edge Research Engine

Run from the repository root:

```powershell
python run_research.py
```

The command validates the frozen 19,470-bar SPY 5-minute cache and the complete `opend_rehab.csv` identity, computes the frozen 36-factor registry, independently replays S01-S03 and six pre-registered filter variants, and writes the repaired version to `outputs/phase3_train_v2/`. The original `phase3_train_v1/` remains immutable.

V2 defines the estimand as the equally weighted trade/event mean. Each bootstrap draw resamples whole trading days and recomputes that same estimand. All hypotheses in a family share one calendar-day index draw; missing events remain zero-count clusters, and untestable pre-registered hypotheses remain in the Holm family size.

The default run also reads the frozen real V3.1.1 RunLog from Downloads and performs one-to-one signal, decision, rejection, and trade parity. It fails closed as `PARITY_FAIL` if the file identity or any comparison fails. Raw as-of-basis prices are converted with the four frozen forward-adjustment coefficients before applying the absolute `1e-9` price tolerance; return tolerance is `1e-12`.

To add a factor, add one frozen row to `registry/FACTOR_REGISTRY.csv`, add the matching deterministic column in `compute_factor_matrix()`, and add a formula test. Do not change an existing row after results have been observed; create a new attempt version instead.

The engine is offline and price-only. It does not use Volume/VWAP, account, position, order, Validation, or OOS data. A 5-minute stop/target collision is recorded as path-uncertain and uses stop-first for the primary result.
