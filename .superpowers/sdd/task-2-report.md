# Task 2 implementation report: Strategy Configuration Contract

## Scope

Implemented only the Task 2 configuration contract: YAML defaults, the checked-in
EMA baseline, `StrategySpec` loading and validation, shared deterministic test
fixtures, and the strategy configuration schema reference. Existing strategy,
data, metrics, and reporting core modules were not modified.

## TDD evidence

### RED

After adding `tests/pipeline/test_strategy_spec.py` and
`tests/pipeline/helpers.py`, the focused test command was run with Python 3.14
and pytest cache disabled:

```powershell
$env:PYTHONPATH = "C:\Users\cbcbe\TradingCodex\tv_quant_system_quant_skills\src"
py -3.14 -m pytest tests/pipeline/test_strategy_spec.py -q -p no:cacheprovider
```

Collection failed as expected because `tv_quant.strategy_spec` did not yet
exist: `ModuleNotFoundError: No module named 'tv_quant.strategy_spec'`.

The initial brief command using the default `python` executable was also
recorded: it resolved to Python 3.12, where pytest is not installed. All actual
verification below used Python 3.14.2.

### GREEN

Focused Task 2 and existing Skill-contract tests:

```powershell
$env:PYTHONPATH = "C:\Users\cbcbe\TradingCodex\tv_quant_system_quant_skills\src"
py -3.14 -m pytest tests/pipeline/test_strategy_spec.py tests/skills/test_skill_contracts.py -q -p no:cacheprovider
```

Result: `8 passed in 0.29s`.

Full regression:

```powershell
$env:PYTHONPATH = "C:\Users\cbcbe\TradingCodex\tv_quant_system_quant_skills\src"
py -3.14 -m pytest tests -q -p no:cacheprovider
```

Result: `30 passed, 5 errors`. The five errors occur during existing tests'
`tmp_path` fixture setup because the environment denies scanning
`C:\Users\cbcbe\AppData\Local\Temp\pytest-of-cbcbe`; no assertion or
application failure was reported.

The same full command was retried with controlled basetemp directories in the
repository and in the explicitly writable Codex workspace. Both retries had
the same `30 passed, 5 errors` test result, followed by pytest cleanup being
denied by the same Windows ACL behavior.

Additional checks:

```powershell
$env:PYTHONPATH = "C:\Users\cbcbe\TradingCodex\tv_quant_system_quant_skills\src"
py -3.14 -m compileall -q src tests
git diff --check
py -3.14 -c "...load checked-in EMA YAML and assert SUPPORTED..."
py -3.14 -c "...assert an RSI-shaped entry rule is blocked..."
```

All additional checks passed.

## Files changed

- `config/backtest-defaults.yaml` — deterministic Phase 1 defaults.
- `config/strategies/ema_baseline.yaml` — checked-in SPY EMA50/EMA200 config.
- `src/tv_quant/strategy_spec.py` — YAML loader, mapping validator, defaults,
  basis-point validation, and the Task 2 fixed-EMA capability seam.
- `tests/pipeline/test_strategy_spec.py` — RED/GREEN contract tests.
- `tests/pipeline/helpers.py` — reusable valid config and deterministic CSV
  fixtures for later tasks.
- `.agents/skills/quant-strategy-spec/references/config-schema.md` — field
  contract, defaults, example, errors, and current-engine mapping.

## Self-review

- Reused `pipeline_models.StrategySpec`, `CapabilityResult`, and
  `CapabilityStatus`; no duplicate model definitions were added.
- Default values are deterministic and commission/slippage are represented as
  non-negative basis points.
- Unknown rule shapes remain in the raw mapping and are blocked rather than
  approximated or translated into generated Python.
- No network, account, order, dependency installation, or secret access was
  performed.
- No existing strategy, data, metrics, or reporting core module was changed.
- The staged commit intentionally excludes test temp directories and this
  report, matching the brief's Task 2 source-file commit scope.

## Concerns and limits

- Five existing tmp-path tests remain unverified in this environment because
  pytest's Windows ACL behavior prevents fixture setup and cleanup. The other
  30 regression tests passed.
- The broader Phase 1 capability matrix is intentionally deferred to Task 3;
  Task 2 only exposes the fixed EMA rule-shape check required by its tests.
- `in_sample_period` and `out_of_sample_period` are reserved fields and map to
  `None` in this Task 2 contract, as specified by the approved implementation;
  non-null period parsing is deferred.

## Fix: reviewer Critical and Important findings

### Changed files

- `src/tv_quant/strategy_spec.py` - Phase 1 capability-boundary blockers,
  strict boolean handling for `optimization_allowed`, rejection of non-null
  unparsed periods, and finite numeric validation for capital, commission, and
  slippage.
- `tests/pipeline/test_strategy_spec.py` - focused coverage for every reviewed
  Phase 1 boundary, boolean and period invalid types, and NaN, infinity, and
  string numeric inputs.
- `.superpowers/sdd/task-2-report.md` - this fix record.

### Covering tests

```powershell
$env:PYTHONPATH = "C:\Users\cbcbe\TradingCodex\tv_quant_system_quant_skills\src"
py -3.14 -m pytest tests/pipeline/test_strategy_spec.py tests/skills/test_skill_contracts.py -q -p no:cacheprovider --basetemp C:\Users\cbcbe\.codex\visualizations\2026\07\24\019f953d-326d-7fa1-a20d-f0f41daaab91\pytest-task2-fix
```

Output: `31 passed in 0.34s`.

```powershell
$env:PYTHONPATH = "C:\Users\cbcbe\TradingCodex\tv_quant_system_quant_skills\src"
py -3.14 -m pytest tests -q -p no:cacheprovider --basetemp C:\Users\cbcbe\.codex\visualizations\2026\07\24\019f953d-326d-7fa1-a20d-f0f41daaab91\pytest-task2-fix-regression
```

Output before pytest's teardown traceback:
`................................E..............EEE....E...`

The regression command exited with code 1 because pytest's session-finish
cleanup was denied access to the controlled basetemp directory:
`PermissionError: [WinError 5] Access is denied`. Pytest aborted before it
printed its normal final summary. The five visible error markers match the
pre-existing `tmp_path` ACL limitation documented above; no new assertion
failure was reported.

Additional checks passed:

```powershell
py -3.14 -m compileall -q src tests
git diff --check
```

### Self-review

- `check_capabilities` now returns a blocker and explicit received-value detail
  for every specified Phase 1 constraint. A data-source-only violation is a
  `DATA_CAPABILITY_BLOCKER`; any strategy constraint is a
  `STRATEGY_CAPABILITY_BLOCKER`.
- `optimization_allowed` accepts only a real Python boolean. Non-null sample
  period fields fail explicitly rather than being mapped to `None`.
- Capital, commission, and slippage reject booleans, non-numeric values, NaN,
  infinity, zero/negative capital, and negative basis points.
- No Task 1 or later-task source files were modified, and no external service,
  package installation, account, or order action was performed.
