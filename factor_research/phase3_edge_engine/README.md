# C1 Phase 3 Edge Research Engine

Run from the repository root:

```powershell
python run_research.py
```

The command validates the frozen 19,470-bar SPY 5-minute cache, computes the frozen 36-factor registry, independently replays S01-S03 and six pre-registered filter variants, applies trading-day clustered inference, and writes versioned artifacts to `outputs/phase3_train_v1/`.

To add a factor, add one frozen row to `registry/FACTOR_REGISTRY.csv`, add the matching deterministic column in `compute_factor_matrix()`, and add a formula test. Do not change an existing row after results have been observed; create a new attempt version instead.

The engine is offline and price-only. It does not use Volume/VWAP, account, position, order, Validation, or OOS data. A 5-minute stop/target collision is recorded as path-uncertain and uses stop-first for the primary result.
