# Task 5: Backtest Audit Data and Rules

## Delivered scope

- Added `AuditContext` and deterministic `audit_backtest` orchestration.
- Added capability precedence, OHLCV validation, strict UTC next-bar fill checks,
  commission/slippage validation, benchmark fairness, optimization prohibition,
  manifest evidence, supplied-artifact checks, concentration warnings, and
  reproducibility hash validation.
- Added focused audit tests and audit-skill evidence/status references.
- Did not modify existing engine, strategy, metrics, data-quality, reporting,
  user-level skills, or later-task files. No network, account, order,
  optimization, VectorBT, push, or pull request action was performed.

## Reproducibility boundary

`data_path` is optional in the declared `AuditContext` manifest shape. When it
is supplied, `sha256_file(Path(manifest["data_path"]))` must match
`manifest["data_hash"]`; non-empty strategy-config and data hashes are always
required. This preserves the brief's supplied baseline context, which supplies
the hashes but no local data path.

## Validation

- `PYTHONPATH=src; py -3.14 -m pytest tests/pipeline/test_backtest_audit.py -q --basetemp .pytest-basetemp-task-5 -p no:cacheprovider`
  - Passed: 6 passed.
- `PYTHONPATH=src; py -3.14 -m pytest tests/test_strategy.py tests/test_metrics.py tests/test_data_quality.py -q -p no:cacheprovider`
  - 17 assertions passed. One existing `tmp_path` fixture setup was blocked by
    `PermissionError` while pytest scanned `C:\Users\cbcbe\AppData\Local\Temp\pytest-of-cbcbe`; it did not reach the test body.
- `py -3.14 -m py_compile src\\tv_quant\\backtest_audit.py`
  - Passed.
- `git diff --cached --check`
  - Passed before commit.

## Commit

`2c3a329 Add deterministic backtest audit`

## Remaining environment limitation

The workspace contains inaccessible historical pytest temporary directories.
They prevent complete pytest fixture cleanup and the one regression test that
requires `tmp_path`; this is unrelated to Task 5 assertions or source logic.

---

## Reviewer-finding fix

### Changed files

- `src/tv_quant/backtest_audit.py`
- `.agents/skills/quant-backtest-audit/SKILL.md`
- `.agents/skills/quant-backtest-audit/references/checks.md`
- `.agents/skills/quant-backtest-audit/references/statuses.md`
- `tests/pipeline/test_backtest_audit.py`

### Fix details

- Artifact evidence now requires existing `summary`, `equity`, `trades`,
  `manifest`, and `audit` files. Empty or partial artifact mappings emit
  `MISSING_ARTIFACT` and cannot pass.
- Added OOS boundary audit. Missing configured periods emits warning issue
  `OOS_BOUNDARY_UNVERIFIED` and yields `CONDITIONAL_PASS`; supplied periods must
  be ordered, non-overlapping, within the strategy range, match manifest locked
  OOS evidence, and bound timestamped data/equity/trade artifacts.
- A single calendar year with 80% or more of positive equity growth now emits
  `ANNUAL_RETURN_CONCENTRATION`, including when it is the only positive year.
- Cost validation now verifies directional `execution_price` from `market_open`
  and configured slippage bps, gross notional, and commission. A raw-open fill
  labelled with non-zero slippage fails with `COST_MISMATCH`.
- The audit test fixture now creates five real temporary artifact files. Added
  focused coverage for required artifacts, absent/overlapping/leaking OOS
  boundaries, single-year concentration, raw-open slippage failure, and SELL
  adverse-slippage pricing.

### Commands and results

- `PYTHONPATH=src; py -3.14 -m pytest tests/pipeline/test_backtest_audit.py -q --basetemp .task-5-fix-pytest -p no:cacheprovider`
  - Environment-only failure: pytest could not clean the sandboxed controlled
    basetemp (`WinError 5`); tests did not enter assertions.
- `PYTHONPATH=src; py -3.14 -m pytest tests/pipeline/test_backtest_audit.py -q --basetemp .task-5-fix-pytest-elevated -p no:cacheprovider`
  - Passed: `11 passed in 0.57s`.
- `PYTHONPATH=src; py -3.14 -m pytest tests/test_strategy.py tests/test_metrics.py tests/test_data_quality.py tests/pipeline/test_strategy_spec.py -q --basetemp .task-5-regression-pytest -p no:cacheprovider`
  - Passed: `49 passed in 0.49s`.
- `PYTHONPATH=src; py -3.14 -m pytest tests/pipeline/test_backtest_audit.py -q --basetemp .task-5-fix-verified -p no:cacheprovider`
  - Passed: `12 passed in 0.49s`.
- `PYTHONPATH=src; py -3.14 -m pytest tests/test_strategy.py tests/test_metrics.py tests/test_data_quality.py tests/pipeline/test_strategy_spec.py -q --basetemp .task-5-regression-verified -p no:cacheprovider`
  - Passed: `49 passed in 0.50s`.
- `git diff --check`
  - Passed.

### Self-review

- Preserved all five `AuditStatus` values and capability-blocker precedence.
- Kept all existing audit checks and added only Task 5 audit-layer evidence.
- Did not change the Task 2 parser, engine, pipeline models, or later tasks.
- No LLM computes trading performance; checks only inspect deterministic inputs
  and configured arithmetic.

### Local commit

`aeadafb Fix Task 5 backtest audit evidence`

---

## Final OOS-evidence fix

### Changed files

- `src/tv_quant/backtest_audit.py`
- `tests/pipeline/test_backtest_audit.py`
- `.agents/skills/quant-backtest-audit/references/checks.md`
- `.superpowers/sdd/task-5-report.md`

### Fix details

- A configured, locked OOS partition now requires `timestamp_utc` evidence for
  data, equity, and trades. Missing columns, empty or invalid timestamps, and
  artifacts without an observation in the locked OOS interval emit
  `OOS_BOUNDARY_FAILURE` with error severity, so the audit cannot pass.
- The valid fixture now includes an OOS trade and remains a `PASS`.
- Added coverage for missing OOS observations in each required artifact and
  for missing equity timestamp evidence. Existing no-trade and annual-growth
  warning checks remain conditional when no OOS partition is configured.

### Commands and results

- `PYTHONPATH=src; py -3.14 -m py_compile src\\tv_quant\\backtest_audit.py`
  - Passed.
- `PYTHONPATH=src; py -3.14 -m pytest tests\\pipeline\\test_backtest_audit.py -q --basetemp .task-5-final-audit-pytest -p no:cacheprovider`
  - Environment-only failure during pytest temporary-directory cleanup:
    `WinError 5`; the sandboxed basetemp could not be scanned.
- `PYTHONPATH=src; py -3.14 -m pytest tests\\pipeline\\test_backtest_audit.py -q --basetemp .task-5-final-audit-pytest-elevated -p no:cacheprovider`
  - Passed: `14 passed in 0.64s`.
- `PYTHONPATH=src; py -3.14 -m pytest tests\\test_strategy.py tests\\test_metrics.py tests\\test_data_quality.py tests\\pipeline\\test_strategy_spec.py -q --basetemp .task-5-final-regression-pytest -p no:cacheprovider`
  - Passed: `49 passed in 0.44s`.
- `git diff --check`
  - Passed.

### Self-review

- The checker requires OOS observations only when both train and locked OOS
  periods are configured; the existing no-boundary conditional behavior is
  unchanged.
- It keeps the prior train/OOS range-leakage protection and does not require
  OOS signal timestamps, because an OOS fill may legitimately be caused by an
  in-sample signal under next-bar execution.
- No Task 2 parser, `pipeline_models`, engine, or later-task file changed.

### Local commit

Created locally with message: `Require OOS evidence in Task 5 audit`.
