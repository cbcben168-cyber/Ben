# Phase 4.3.2 implementation evidence

- Recorded at: `2026-10-13T03:53:38.0256949+08:00`
- Branch: `codex/futu-factor-progress-dashboard-v1`
- Verified HEAD: `03eab2410ab7738b06601452b28b42f979e7fbb7`
- Phase 4.3.1 checkpoint: `a0d43e0380b78c96759e55dbddf5b77b44e4c648`
- Python: `3.14.2`
- pytest: `9.1.1`

## Corrected-preflight readiness verification

Command:

```powershell
$env:PYTHONPATH="src"
py -3.14 -m factor_research.phase4_mechanism_study.phase432_structural_preflight --verify-ready-only
```

Result: exit code `0`, status `PHASE4_3_2_LAUNCH_READY`.

Verified source hashes:

- `input_integrity.py`: `fb32e373130542a736114f2e0cfdaba81a123bba4511ca4e98b1ec9045d72cf6`
- `lifecycle.py`: `52d54a1f7e334d2d87a8c2bc83a17ed6c964a5f948f8bd25cbd7f809732da952`
- `phase432_structural_preflight.py`: `e6ce94bbb59ce118a9523755f6e2de6b44f6eaa5a46bcff3376f53d479192c88`
- frozen `structural_preflight.py`: `d3edde168f4ac29c526c0a858dc713b681fb16fa8fdfc584a47d8928bfaf553d`

This verification checked registration, source hashes, the Phase 4.3.1 checkpoint ancestry,
the clean tracked worktree requirement, and absence of a prior V2 attempt. It did not run
the structural scan or calculate signals, trades, or performance.

## Full repository test

Command:

```powershell
$env:PYTHONPATH="src"
py -3.14 -m pytest -q
```

Result: exit code `0`.

```text
380 passed in 120.01s (0:02:00)
```

## Frozen V1 preservation

The V1 runner, V1 runner test, and V1 output manifest retain their incident-recorded hashes:

- `phase4_train_runner.py`: `c45b2454c192bb241cb93bf1f81a2310fceeec8de06573df49da0904fa3a692b`
- `tests/test_phase4_train_runner.py`: `d65b46846ea8fb1be9a78fb47d86442f109419227662df44a670778f44168f4c`
- `outputs/phase4_train_v1/manifest.json`: `682bf9f4cf4eb97bb1f20899b58659909d83c862a1e03df0f95ba55c7151bc49`

## Execution boundary

- Real corrected structural preflight: `NOT_RUN`
- TRAIN runner: `NOT_RUN`
- Historical simulator or return calculation: `NOT_RUN`
- Validation/OOS access: `NOT_AUTHORIZED`
- Dashboard data cleanup: `NOT_PERFORMED`
