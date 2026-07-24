# Quant Research Skills Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 建立三个项目级量化研究 Skill，将中文策略标准化、现有 EMA 基线回测、数据质量检查、Buy and Hold 比较和回测审计串联为可重复的一键流程。

**Architecture:** 用项目级 Skill 负责自然语言入口和固定执行顺序，用结构化 YAML 保存策略和假设，用现有本地 Python 模块完成计算，用独立审计逻辑阻止不受支持或不可信的结果。第一阶段不引入 VectorBT、期权回测、参数优化或实盘交易。

**Tech Stack:** Codex project Skills、Python 3.12、PowerShell、YAML、pytest、现有 tv_quant 模块、Futu 本地缓存和现有报告系统。

## Global Constraints

- 第一阶段只包装和编排现有真实能力。
- 当前正式基线仅支持 SPY、QQQ、1d 日线和现有固定 EMA50/EMA200 多头规则。
- 所有内部时间使用 UTC，默认 fill_timing 为 next_bar。
- 手续费和滑点必须显式进入配置、回测调用、报告和审计。
- Buy and Hold 必须使用相同标的、时间范围、资金、价格和成本假设。
- data_source 默认 validated_local_cache_first；yfinance 只允许显式 smoke test。
- optimization_allowed 默认 false；第一阶段不执行参数搜索、Monte Carlo、Walk-forward 或多策略比较。
- 不支持的策略返回 STRATEGY_CAPABILITY_BLOCKER。
- 数据不可用返回 DATA_CAPABILITY_BLOCKER。
- 不连接实盘账户、IBKR、TradingView 执行链路，也不创建或发送订单。
- 不修改原始行情数据、现有 Phase 1 数据契约或 requirements.txt。
- 不依赖未固定版本的用户级 Skill，不安装完整外部 Skill 套件。
- 每个实施任务独立提交，不推送远程。

---

## Planned File Map

| Path | Create/Modify | Responsibility |
|---|---|---|
| .agents/skills/quant-strategy-spec/SKILL.md | Create | 中文策略到 YAML 的入口和能力检查 |
| .agents/skills/quant-strategy-spec/references/config-schema.md | Create | 配置字段、默认值和 EMA 映射 |
| .agents/skills/quant-research-pipeline/SKILL.md | Create | 固定 Stage 0 至 Stage 7 的总控入口 |
| .agents/skills/quant-research-pipeline/references/stages.md | Create | 阶段顺序和停止规则 |
| .agents/skills/quant-backtest-audit/SKILL.md | Create | 审计入口和五种状态 |
| .agents/skills/quant-backtest-audit/references/checks.md | Create | 审计检查和证据要求 |
| config/backtest-defaults.yaml | Create | 受控默认成本、成交、来源和报告选项 |
| config/strategies/ema_baseline.yaml | Create | SPY EMA50/EMA200 示例配置 |
| src/tv_quant/pipeline_models.py | Create | 共享枚举和数据类 |
| src/tv_quant/strategy_spec.py | Create | YAML 读取、字段验证和能力检查 |
| src/tv_quant/run_manifest.py | Create | 配置、数据和运行文件的 SHA-256 |
| src/tv_quant/backtest_audit.py | Create | 回测证据检查和五态审计结果 |
| src/tv_quant/research_pipeline.py | Create | 数据、回测、基准、审计和报告编排 |
| src/tv_quant/pipeline_cli.py | Create | CLI 参数和退出码 |
| scripts/quant/run_pipeline.ps1 | Create | Windows 一键入口，不安装依赖 |
| tests/skills/test_skill_contracts.py | Create | Skill 发现和 frontmatter 验证 |
| tests/pipeline/test_strategy_spec.py | Create | 配置契约和默认值 |
| tests/pipeline/helpers.py | Create | 确定性配置和 CSV fixture helper |
| tests/pipeline/test_capabilities.py | Create | capability 状态和 blocker |
| tests/pipeline/test_run_manifest.py | Create | 哈希和运行清单 |
| tests/pipeline/test_backtest_audit.py | Create | 审计规则和五种状态 |
| tests/pipeline/test_research_pipeline.py | Create | 阶段顺序和停止规则 |
| tests/pipeline/test_pipeline_cli.py | Create | CLI 参数和退出码 |
| tests/pipeline/test_run_pipeline_script.py | Create | PowerShell 静态契约 |
| tests/pipeline/test_ema_acceptance.py | Create | EMA smoke test 和 RSI blocker |
| AGENTS.md | Modify | 追加简短的流水线入口和安全默认值 |
| src/tv_quant/data_quality.py | Do not modify | 继续作为 OHLCV 校验来源 |
| src/tv_quant/strategy.py | Do not modify | 继续作为固定 EMA 回测来源 |
| src/tv_quant/metrics.py | Do not modify | 继续作为指标和 Buy and Hold 来源 |
| src/tv_quant/reporting.py | Do not modify | 继续作为基础 JSON/CSV 报告来源 |
| src/tv_quant/cli.py | Do not modify initially | 复用现有 cli.main 和命令 |
| requirements.txt | Do not modify | 不增加依赖 |

---

## Shared Interfaces

~~~python
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class CapabilityStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    STRATEGY_CAPABILITY_BLOCKER = "STRATEGY_CAPABILITY_BLOCKER"
    DATA_CAPABILITY_BLOCKER = "DATA_CAPABILITY_BLOCKER"


class AuditStatus(str, Enum):
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"
    STRATEGY_CAPABILITY_BLOCKER = "STRATEGY_CAPABILITY_BLOCKER"
    DATA_CAPABILITY_BLOCKER = "DATA_CAPABILITY_BLOCKER"


@dataclass(frozen=True)
class StrategySpec:
    strategy_name: str
    asset_class: str
    symbol: str
    benchmark: str
    timeframe: str
    start_date: date
    end_date: date
    initial_capital: float
    entry_rules: tuple[Mapping[str, Any], ...]
    exit_rules: tuple[Mapping[str, Any], ...]
    position_sizing: Mapping[str, Any]
    commission_bps: float
    slippage_bps: float
    fill_timing: str
    data_source: str
    in_sample_period: tuple[date, date] | None
    out_of_sample_period: tuple[date, date] | None
    optimization_allowed: bool
    report_language: str
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class CapabilityResult:
    status: CapabilityStatus
    reasons: tuple[str, ...]
    required_data: tuple[str, ...]
    required_engine: tuple[str, ...]


@dataclass(frozen=True)
class AuditIssue:
    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class AuditReport:
    status: AuditStatus
    checks: Mapping[str, bool]
    issues: tuple[AuditIssue, ...]
    warnings: tuple[str, ...]
~~~

后续任务只能使用这些名称和状态值。

## Task 1: Skill Contract and Shared Model Foundation

**Files:**
- Create: .agents/skills/quant-strategy-spec/SKILL.md
- Create: .agents/skills/quant-research-pipeline/SKILL.md
- Create: .agents/skills/quant-backtest-audit/SKILL.md
- Create: src/tv_quant/pipeline_models.py
- Create: tests/skills/test_skill_contracts.py

**Interfaces:**
- Consumes: project root, three fixed Skill directory names, and the shared enums/dataclasses above.
- Produces: discoverable Skill documents and importable shared types for Tasks 2, 5, and 6.

- [ ] **Step 1: Write the failing discovery test**

Create tests/skills/test_skill_contracts.py:

~~~python
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / ".agents" / "skills"
EXPECTED = {
    "quant-strategy-spec",
    "quant-research-pipeline",
    "quant-backtest-audit",
}


def read_frontmatter(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---"
    closing = lines[1:].index("---") + 1
    result = yaml.safe_load("\n".join(lines[1:closing]))
    assert isinstance(result, dict)
    return result


def test_project_skills_are_discoverable_and_unique():
    paths = sorted(SKILL_ROOT.glob("*/SKILL.md"))
    assert {path.parent.name for path in paths} == EXPECTED
    frontmatters = [read_frontmatter(path) for path in paths]
    names = [item["name"] for item in frontmatters]
    assert names == sorted(EXPECTED)
    assert len(names) == len(set(names))
    assert all(item["description"].strip() for item in frontmatters)


def test_skill_documents_do_not_add_execution_or_global_dependencies():
    for path in sorted(SKILL_ROOT.glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8").lower()
        assert "submit_order" not in text
        assert "place_order" not in text
        assert "alphagbm" not in text
        assert "c:\\users\\" not in text
~~~

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/skills/test_skill_contracts.py -q
~~~
Expected: FAIL because the three project Skill documents do not exist.

- [ ] **Step 2: Create the three non-empty Skill documents**

Use one frontmatter block per file:

~~~markdown
---
name: quant-strategy-spec
description: Convert Chinese trading rules into validated YAML and block unsupported capabilities before data access or backtesting.
---

# quant-strategy-spec

输入中文策略规则，生成配置并调用 Python 验证；不下载数据、不运行回测、不发送订单。
~~~

~~~markdown
---
name: quant-research-pipeline
description: Run the fixed local quant research workflow from validated strategy configuration through data checks, EMA baseline, benchmark, audit, and Chinese report.
---

# quant-research-pipeline

只调用固定 pipeline CLI，按 Stage 0 至 Stage 7 顺序运行；失败或 blocker 状态停止后续阶段。
~~~

~~~markdown
---
name: quant-backtest-audit
description: Audit deterministic backtest evidence for timing, costs, data quality, benchmark fairness, hashes, reproducibility, and capability limits.
---

# quant-backtest-audit

读取运行清单、交易明细、权益曲线和配置，输出五种审计状态；不执行交易。
~~~

- [ ] **Step 3: Create pipeline_models.py**

Create src/tv_quant/pipeline_models.py with the Shared Interfaces block and imports only from dataclasses, datetime, enum, pathlib, and typing. Do not import pandas, Futu, yfinance, or a Skill.

Run:
~~~text
$env:PYTHONPATH = "src"
python -c "from tv_quant.pipeline_models import AuditStatus, CapabilityStatus, StrategySpec; print(AuditStatus.PASS.value, CapabilityStatus.SUPPORTED.value, StrategySpec.__name__)"
~~~
Expected: PASS SUPPORTED StrategySpec.

- [ ] **Step 4: Run focused and existing tests**

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/skills/test_skill_contracts.py -q
python -m pytest tests -q -p no:cacheprovider
~~~
Expected: two Skill tests and all existing tests pass.

- [ ] **Step 5: Commit**

Run:
~~~text
git add .agents/skills/quant-strategy-spec/SKILL.md .agents/skills/quant-research-pipeline/SKILL.md .agents/skills/quant-backtest-audit/SKILL.md src/tv_quant/pipeline_models.py tests/skills/test_skill_contracts.py
git commit -m "Add quant research Skill contracts"
~~~
Expected: one commit containing only Task 1 files.

---

## Task 2: Strategy Configuration Contract

**Files:**
- Create: config/backtest-defaults.yaml
- Create: config/strategies/ema_baseline.yaml
- Create: src/tv_quant/strategy_spec.py
- Create: tests/pipeline/test_strategy_spec.py
- Create: tests/pipeline/helpers.py
- Create: .agents/skills/quant-strategy-spec/references/config-schema.md

**Interfaces:**
- Consumes: pipeline_models.StrategySpec and the Skill documents from Task 1.
- Produces: load_strategy_spec(path: Path) -> StrategySpec, validate_strategy_mapping(payload: Mapping[str, Any]) -> StrategySpec, and reusable tests/pipeline/helpers.py fixtures.

- [ ] **Step 1: Write failing configuration tests**

Create tests/pipeline/helpers.py with the shared valid_payload function:

~~~python
def valid_payload():
    return {
        "strategy_name": "ema_baseline",
        "asset_class": "equity",
        "symbol": "SPY",
        "benchmark": "buy_and_hold",
        "timeframe": "1d",
        "start_date": "2020-01-01",
        "end_date": "2024-12-31",
        "initial_capital": 100000,
        "entry_rules": [{"type": "ema_crossover", "fast_period": 50, "slow_period": 200}],
        "exit_rules": [{"type": "ema_crossunder"}],
        "position_sizing": {"type": "cash_limited_long_only"},
        "commission_model": {"type": "basis_points", "value": 5},
        "slippage_model": {"type": "basis_points", "value": 5},
    }
~~~

Import it in tests/pipeline/test_strategy_spec.py and create the tests below:

~~~python
from datetime import date
from pathlib import Path
import pytest

from tv_quant.pipeline_models import StrategySpec
from tv_quant.strategy_spec import (
    check_capabilities,
    load_strategy_spec,
    validate_strategy_mapping,
)


from tests.pipeline.helpers import valid_payload


def test_defaults_and_ema_mapping_are_deterministic():
    spec = validate_strategy_mapping(valid_payload())
    assert isinstance(spec, StrategySpec)
    assert spec.symbol == "SPY"
    assert spec.fill_timing == "next_bar"
    assert spec.optimization_allowed is False
    assert spec.report_language == "zh-CN"
    assert spec.data_source == "validated_local_cache_first"
    assert spec.commission_bps == 5
    assert spec.slippage_bps == 5
    assert spec.start_date == date(2020, 1, 1)


def test_checked_in_ema_yaml_is_supported():
    spec = load_strategy_spec(Path("config/strategies/ema_baseline.yaml"))
    assert spec.strategy_name == "ema_baseline"
    assert check_capabilities(spec).status.value == "SUPPORTED"


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda data: data.pop("symbol"), "missing required field: symbol"),
        (lambda data: data.update({"start_date": "2025-01-01"}), "start_date must precede end_date"),
        (lambda data: data.update({"commission_model": {"type": "basis_points", "value": -1}}), "commission"),
        (lambda data: data.update({"initial_capital": 0}), "initial_capital"),
    ],
)
def test_invalid_strategy_config_is_rejected(mutator, message):
    payload = valid_payload()
    mutator(payload)
    with pytest.raises(ValueError, match=message):
        validate_strategy_mapping(payload)
~~~

The same tests/pipeline/helpers.py file must also define these deterministic helpers for later tasks:

~~~python
from pathlib import Path
import pandas as pd
import yaml


def write_ema_config(root: Path) -> Path:
    payload = valid_payload()
    payload["end_date"] = "2020-10-15"
    path = root / "ema.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def write_rsi_config(root: Path) -> Path:
    payload = valid_payload()
    payload["end_date"] = "2020-10-15"
    payload["entry_rules"] = [{"type": "rsi", "period": 2, "less_than": 10}]
    path = root / "rsi.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def write_crossover_csv(path: Path) -> None:
    dates = pd.date_range("2020-01-01", periods=203, freq="B", tz="UTC")
    close = [100.0] * 200 + [200.0, 200.0, 200.0]
    opens = [100.0] * 200 + [100.0, 150.0, 200.0]
    frame = pd.DataFrame({
        "timestamp_utc": dates,
        "ticker": ["SPY"] * len(dates),
        "open": opens,
        "high": [max(o, c) + 1 for o, c in zip(opens, close)],
        "low": [min(o, c) - 1 for o, c in zip(opens, close)],
        "close": close,
        "volume": [1_000_000] * len(dates),
    })
    frame.to_csv(path, index=False)


def write_valid_spy_csv(path: Path) -> None:
    write_crossover_csv(path)


def write_invalid_csv(path: Path) -> None:
    write_crossover_csv(path)
    frame = pd.read_csv(path)
    frame.loc[10, "close"] = None
    frame.to_csv(path, index=False)
~~~

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/pipeline/test_strategy_spec.py -q
~~~
Expected: FAIL because strategy_spec.py and the checked-in YAML do not exist.

- [ ] **Step 2: Create the default configuration**

Create config/backtest-defaults.yaml:

~~~yaml
benchmark: buy_and_hold
fill_timing: next_bar
optimization_allowed: false
report_language: zh-CN
data_source: validated_local_cache_first
commission_model:
  type: basis_points
  value: 5
slippage_model:
  type: basis_points
  value: 5
~~~

Create config/strategies/ema_baseline.yaml:

~~~yaml
strategy_name: ema_baseline
asset_class: equity
symbol: SPY
benchmark: buy_and_hold
timeframe: 1d
start_date: "2020-01-01"
end_date: "2024-12-31"
initial_capital: 100000
entry_rules:
  - type: ema_crossover
    fast_period: 50
    slow_period: 200
exit_rules:
  - type: ema_crossunder
position_sizing:
  type: cash_limited_long_only
commission_model:
  type: basis_points
  value: 5
slippage_model:
  type: basis_points
  value: 5
fill_timing: next_bar
data_source: validated_local_cache_first
in_sample_period: null
out_of_sample_period: null
optimization_allowed: false
report_language: zh-CN
~~~

- [ ] **Step 3: Implement parsing and validation**

Create src/tv_quant/strategy_spec.py with these public functions:

~~~python
from datetime import date
from pathlib import Path
from typing import Any, Mapping
import yaml

from .pipeline_models import CapabilityResult, CapabilityStatus, StrategySpec

DEFAULTS = {
    "benchmark": "buy_and_hold",
    "fill_timing": "next_bar",
    "optimization_allowed": False,
    "report_language": "zh-CN",
    "data_source": "validated_local_cache_first",
}
REQUIRED_FIELDS = (
    "strategy_name", "asset_class", "symbol", "timeframe",
    "start_date", "end_date", "initial_capital", "entry_rules",
    "exit_rules", "position_sizing", "commission_model", "slippage_model",
)


def _parse_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO date") from error


def validate_strategy_mapping(payload: Mapping[str, Any]) -> StrategySpec:
    data = dict(DEFAULTS)
    data.update(payload)
    for field in REQUIRED_FIELDS:
        if field not in data:
            raise ValueError(f"missing required field: {field}")
    start_date = _parse_date(data["start_date"], "start_date")
    end_date = _parse_date(data["end_date"], "end_date")
    if start_date >= end_date:
        raise ValueError("start_date must precede end_date")
    initial_capital = float(data["initial_capital"])
    if initial_capital <= 0:
        raise ValueError("initial_capital must be positive")
    if not isinstance(data["entry_rules"], list) or not data["entry_rules"]:
        raise ValueError("entry_rules must be a non-empty list")
    if not isinstance(data["exit_rules"], list) or not data["exit_rules"]:
        raise ValueError("exit_rules must be a non-empty list")
    commission = data["commission_model"]
    slippage = data["slippage_model"]
    if commission.get("type") != "basis_points" or float(commission["value"]) < 0:
        raise ValueError("commission_model must use non-negative basis points")
    if slippage.get("type") != "basis_points" or float(slippage["value"]) < 0:
        raise ValueError("slippage_model must use non-negative basis points")
    return StrategySpec(
        strategy_name=str(data["strategy_name"]),
        asset_class=str(data["asset_class"]),
        symbol=str(data["symbol"]).upper(),
        benchmark=str(data["benchmark"]),
        timeframe=str(data["timeframe"]),
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        entry_rules=tuple(data["entry_rules"]),
        exit_rules=tuple(data["exit_rules"]),
        position_sizing=dict(data["position_sizing"]),
        commission_bps=float(commission["value"]),
        slippage_bps=float(slippage["value"]),
        fill_timing=str(data["fill_timing"]),
        data_source=str(data["data_source"]),
        in_sample_period=None,
        out_of_sample_period=None,
        optimization_allowed=bool(data["optimization_allowed"]),
        report_language=str(data["report_language"]),
        raw=data,
    )


def load_strategy_spec(path: Path) -> StrategySpec:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("strategy config must be a YAML mapping")
    return validate_strategy_mapping(payload)


def check_capabilities(spec: StrategySpec, *, allow_smoke_test_data=False):
    reasons = []
    if spec.asset_class != "equity":
        reasons.append("asset_class is not supported")
    if spec.symbol not in {"SPY", "QQQ"}:
        reasons.append("symbol is not supported")
    if spec.timeframe != "1d":
        reasons.append("timeframe is not supported")
    if spec.benchmark != "buy_and_hold":
        reasons.append("benchmark must be buy_and_hold")
    if spec.fill_timing != "next_bar":
        reasons.append("fill_timing must be next_bar")
    if spec.optimization_allowed:
        reasons.append("optimization_allowed must be false in Phase 1")
    if spec.data_source == "yfinance" and not allow_smoke_test_data:
        reasons.append("yfinance requires explicit smoke-test mode")
    if spec.data_source not in {"validated_local_cache_first", "yfinance"}:
        reasons.append("data_source is not supported")
    if spec.entry_rules != (
        {"type": "ema_crossover", "fast_period": 50, "slow_period": 200},
    ):
        reasons.append("only fixed EMA50/EMA200 crossover is supported")
    if spec.exit_rules != ({"type": "ema_crossunder"},):
        reasons.append("only fixed EMA crossunder exit is supported")
    if spec.position_sizing.get("type") != "cash_limited_long_only":
        reasons.append("position sizing is not supported")
    if reasons:
        status = CapabilityStatus.STRATEGY_CAPABILITY_BLOCKER
        if spec.data_source == "yfinance" and not allow_smoke_test_data and len(reasons) == 1:
            status = CapabilityStatus.DATA_CAPABILITY_BLOCKER
        return CapabilityResult(status, tuple(reasons), ("daily OHLCV",), ("fixed EMA50/EMA200",))
    return CapabilityResult(
        CapabilityStatus.SUPPORTED,
        (),
        ("validated standardized daily OHLCV",),
        ("tv_quant.strategy.run_backtest",),
    )
~~~

Unknown nested rule shapes remain in raw configuration and are rejected by check_capabilities; no rule is silently transformed.

- [ ] **Step 4: Add config-schema.md**

Document all 20 fields, YAML example, defaults, required fields, Python types, validation errors, and the mapping to the fixed current engine. State that the Skill produces YAML while Python produces all numeric results.

- [ ] **Step 5: Run focused and regression tests**

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/pipeline/test_strategy_spec.py tests/skills/test_skill_contracts.py -q
python -m pytest tests -q -p no:cacheprovider
~~~
Expected: focused tests and all existing tests pass.

- [ ] **Step 6: Commit**

Run:
~~~text
git add config/backtest-defaults.yaml config/strategies/ema_baseline.yaml src/tv_quant/strategy_spec.py tests/pipeline/test_strategy_spec.py .agents/skills/quant-strategy-spec/references/config-schema.md
git commit -m "Add strategy configuration contract"
~~~
Expected: one commit containing Task 2 files.

---

## Task 3: Capability Matrix and Blockers

**Files:**
- Modify: src/tv_quant/strategy_spec.py: check_capabilities
- Create: .agents/skills/quant-strategy-spec/references/capability-matrix.md
- Create: tests/pipeline/test_capabilities.py

**Interfaces:**
- Consumes: StrategySpec from Task 2.
- Produces: CapabilityResult with SUPPORTED, STRATEGY_CAPABILITY_BLOCKER, or DATA_CAPABILITY_BLOCKER before data refresh or backtest.

- [ ] **Step 1: Write blocker tests**

Create tests/pipeline/test_capabilities.py:

~~~python
from tv_quant.pipeline_models import CapabilityStatus
from tv_quant.strategy_spec import check_capabilities, validate_strategy_mapping
from tests.pipeline.helpers import valid_payload
import pytest


@pytest.mark.parametrize(
    ("field", "value", "status"),
    [
        ("symbol", "IWM", CapabilityStatus.STRATEGY_CAPABILITY_BLOCKER),
        ("timeframe", "30m", CapabilityStatus.STRATEGY_CAPABILITY_BLOCKER),
        ("optimization_allowed", True, CapabilityStatus.STRATEGY_CAPABILITY_BLOCKER),
        ("data_source", "ibkr", CapabilityStatus.STRATEGY_CAPABILITY_BLOCKER),
    ],
)
def test_unsupported_capability_is_blocked(field, value, status):
    payload = valid_payload()
    payload[field] = value
    result = check_capabilities(validate_strategy_mapping(payload))
    assert result.status is status


def test_rsi_is_blocked_without_approximation():
    payload = valid_payload()
    payload["entry_rules"] = [{"type": "rsi", "period": 2, "less_than": 10}]
    result = check_capabilities(validate_strategy_mapping(payload))
    assert result.status is CapabilityStatus.STRATEGY_CAPABILITY_BLOCKER
    assert "EMA" in " ".join(result.reasons)


def test_yfinance_requires_explicit_smoke_test_mode():
    payload = valid_payload()
    payload["data_source"] = "yfinance"
    spec = validate_strategy_mapping(payload)
    assert check_capabilities(spec).status is CapabilityStatus.DATA_CAPABILITY_BLOCKER
    assert check_capabilities(spec, allow_smoke_test_data=True).status is CapabilityStatus.SUPPORTED
~~~

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/pipeline/test_capabilities.py -q
~~~
Expected: FAIL until the explicit status and reason behavior exists.

- [ ] **Step 2: Implement explicit matrix behavior**

Run checks in this order: asset class and symbol; timeframe; benchmark and fill timing; optimization flag; data source; rule shape; position sizing. Return stable English reasons. Do not add RSI, MACD, 30m data, multi-symbol input, IBKR, LEAN, TradingView execution, options, generated Python rules, or order paths.

- [ ] **Step 3: Document the matrix**

Create capability-matrix.md with this table:

| Request | Status | Data access | Backtest access |
|---|---|---|---|
| SPY/QQQ fixed EMA50/EMA200, 1d | SUPPORTED | Continue to local-cache check | Allowed |
| RSI or MACD | STRATEGY_CAPABILITY_BLOCKER | Stop | Not called |
| 30m/60m or multi-symbol | STRATEGY_CAPABILITY_BLOCKER | Stop | Not called |
| yfinance without smoke flag | DATA_CAPABILITY_BLOCKER | Stop | Not called |
| Missing local cache | DATA_CAPABILITY_BLOCKER | Stop after cache check | Not called |
| IBKR, LEAN, TradingView execution | STRATEGY_CAPABILITY_BLOCKER | Stop | Not called |
| Options or option-chain request | DATA_CAPABILITY_BLOCKER | Stop | Not called |
| optimization_allowed=true | STRATEGY_CAPABILITY_BLOCKER | Stop | Not called |
| Order or live-account request | STRATEGY_CAPABILITY_BLOCKER | Stop | Not called |

- [ ] **Step 4: Verify no side effects**

Add a test that replaces future refresh and backtest callables with functions raising AssertionError, sends an RSI spec through the future pipeline entry point, and verifies the blocker is returned with neither callable invoked.

- [ ] **Step 5: Run tests and commit**

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/pipeline/test_capabilities.py tests/pipeline/test_strategy_spec.py tests/skills/test_skill_contracts.py -q
git diff --check
~~~
Expected: all focused tests pass and no whitespace error is reported.

Commit:
~~~text
git add src/tv_quant/strategy_spec.py tests/pipeline/test_capabilities.py .agents/skills/quant-strategy-spec/references/capability-matrix.md
git commit -m "Add strategy capability blockers"

## Task 4: quant-strategy-spec Skill and References

**Files:**
- Modify: .agents/skills/quant-strategy-spec/SKILL.md
- Create: .agents/skills/quant-strategy-spec/references/input-output.md
- Create: tests/skills/test_strategy_spec_skill.py

**Interfaces:**
- Consumes: config-schema.md, capability-matrix.md, load_strategy_spec, validate_strategy_mapping, and check_capabilities.
- Produces: a short project Skill that emits a validated YAML path or a blocker without data or backtest execution.

- [ ] **Step 1: Write the Skill behavior tests**

Create tests/skills/test_strategy_spec_skill.py:

~~~python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".agents" / "skills" / "quant-strategy-spec" / "SKILL.md"


def test_skill_declares_non_execution_boundary():
    text = SKILL.read_text(encoding="utf-8")
    assert "YAML" in text
    assert "capability" in text.lower()
    assert "不下载数据" in text
    assert "不运行回测" in text
    assert "不发送订单" in text
    assert "references/config-schema.md" in text
    assert "references/capability-matrix.md" in text


def test_skill_references_ema_and_rsi_examples():
    text = (SKILL.parent / "references" / "input-output.md").read_text(encoding="utf-8")
    assert "ema_crossover" in text
    assert "RSI" in text
    assert "STRATEGY_CAPABILITY_BLOCKER" in text
    assert "optimization_allowed: false" in text
~~~

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/skills/test_strategy_spec_skill.py -q
~~~
Expected: FAIL until the Skill references are expanded.

- [ ] **Step 2: Write the executable Skill contract**

The Skill body must state these rules in Chinese:

1. Read natural-language strategy text.
2. Ask for missing symbol, timeframe, dates, capital, entry, exit, cost, and fill assumptions rather than guessing.
3. Produce YAML using the 20-field schema.
4. Call Python validation and capability check.
5. Return the config path and compact assumptions on success.
6. Return STRATEGY_CAPABILITY_BLOCKER or DATA_CAPABILITY_BLOCKER on failure.
7. Never call download, backtest, order, broker, TradingView execution, or an unpinned user-level Skill.
8. Defaults are optimization_allowed=false, report_language=zh-CN, benchmark=Buy and Hold, fill_timing=next_bar, and data_source=validated_local_cache_first.

- [ ] **Step 3: Create input-output.md**

Include this valid EMA example:

~~~yaml
strategy_name: ema_baseline
symbol: SPY
timeframe: 1d
entry_rules:
  - type: ema_crossover
    fast_period: 50
    slow_period: 200
exit_rules:
  - type: ema_crossunder
fill_timing: next_bar
optimization_allowed: false
~~~

Include this RSI response shape:

~~~text
STRATEGY_CAPABILITY_BLOCKER
unsupported_rule: RSI(2) < 10
reason: current engine supports only fixed EMA50/EMA200
next_development_request: add a versioned RSI signal contract and tests before enabling it
~~~

- [ ] **Step 4: Run tests and commit**

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/skills/test_strategy_spec_skill.py tests/pipeline/test_capabilities.py -q
~~~
Expected: all Skill and capability tests pass.

Commit:
~~~text
git add .agents/skills/quant-strategy-spec/SKILL.md .agents/skills/quant-strategy-spec/references/input-output.md tests/skills/test_strategy_spec_skill.py
git commit -m "Define quant strategy specification Skill"
~~~

---

## Task 5: Backtest Audit Data and Rules

**Files:**
- Create: src/tv_quant/backtest_audit.py
- Create: .agents/skills/quant-backtest-audit/references/checks.md
- Create: .agents/skills/quant-backtest-audit/references/statuses.md
- Modify: .agents/skills/quant-backtest-audit/SKILL.md
- Create: tests/pipeline/test_backtest_audit.py

**Interfaces:**
- Consumes: StrategySpec, CapabilityResult, pandas data/equity/trades, strategy metrics, Buy and Hold return, manifest mapping, and artifact paths.
- Produces: audit_backtest(context: AuditContext) -> AuditReport.

Define this public input at the top of src/tv_quant/backtest_audit.py:

~~~python
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
import pandas as pd

from .pipeline_models import AuditReport, CapabilityResult, StrategySpec


@dataclass(frozen=True)
class AuditContext:
    spec: StrategySpec
    capability: CapabilityResult
    data: pd.DataFrame
    equity: pd.DataFrame
    trades: pd.DataFrame
    strategy_metrics: Mapping[str, Any]
    benchmark_return: float
    manifest: Mapping[str, Any]
    artifact_paths: Mapping[str, Path]
~~~

- [ ] **Step 1: Write the audit tests**

Create tests/pipeline/test_backtest_audit.py with deterministic rows based on tests/test_strategy.py crossover_data. Cover these assertions:

~~~python
def test_next_bar_fill_passes_for_existing_trade_shape():
    report = audit_backtest(valid_context())
    assert report.status is AuditStatus.PASS
    assert report.checks["next_bar_fill"] is True


def test_same_bar_fill_is_fail():
    context = replace(
        valid_context(),
        trades=valid_context().trades.assign(
            signal_timestamp_utc=valid_context().trades["timestamp_utc"]
        ),
    )
    report = audit_backtest(context)
    assert report.status is AuditStatus.FAIL
    assert any(issue.code == "SAME_BAR_SIGNAL_FILL" for issue in report.issues)


def test_cost_mismatch_is_fail():
    context = replace(
        valid_context(),
        trades=valid_context().trades.assign(commission=0.0, slippage_bps=0.0),
    )
    report = audit_backtest(context)
    assert report.status is AuditStatus.FAIL
    assert any(issue.code == "COST_MISMATCH" for issue in report.issues)


def test_empty_trades_are_conditional():
    report = audit_backtest(replace(valid_context(), trades=empty_trades()))
    assert report.status is AuditStatus.CONDITIONAL_PASS
    assert any(issue.code == "NO_TRADES" for issue in report.issues)


def test_missing_artifact_is_fail():
    context = replace(valid_context(), artifact_paths={"summary": Path("missing-summary.json")})
    assert audit_backtest(context).status is AuditStatus.FAIL


def test_capability_blocker_is_returned():
    capability = CapabilityResult(
        CapabilityStatus.STRATEGY_CAPABILITY_BLOCKER,
        ("RSI is unsupported",),
        ("daily OHLCV",),
        ("fixed EMA50/EMA200",),
    )
    report = audit_backtest(replace(valid_context(), capability=capability))
    assert report.status is AuditStatus.STRATEGY_CAPABILITY_BLOCKER
~~~

At the top of this test module define every helper used above:

~~~python
from dataclasses import replace
from pathlib import Path
import pandas as pd

from tv_quant.backtest_audit import AuditContext, audit_backtest
from tv_quant.pipeline_models import AuditStatus, CapabilityResult, CapabilityStatus
from tv_quant.strategy_spec import check_capabilities, validate_strategy_mapping
from tests.pipeline.helpers import valid_payload


def empty_trades():
    return pd.DataFrame(columns=[
        "timestamp_utc", "side", "shares", "signal_timestamp_utc", "market_open",
        "execution_price", "slippage_bps", "gross_notional", "commission", "net_cash_flow",
    ])


def valid_context():
    spec = validate_strategy_mapping(valid_payload())
    data = pd.DataFrame({
        "timestamp_utc": pd.date_range("2020-01-01", periods=2, tz="UTC"),
        "ticker": ["SPY", "SPY"],
        "open": [100.0, 101.0], "high": [101.0, 102.0],
        "low": [99.0, 100.0], "close": [100.0, 101.0], "volume": [1000, 1000],
    })
    equity = pd.DataFrame({
        "timestamp_utc": data["timestamp_utc"],
        "equity": [100000.0, 100100.0],
        "daily_return": [0.0, 0.001],
    })
    trades = pd.DataFrame([{
        "timestamp_utc": data.loc[1, "timestamp_utc"], "side": "BUY", "shares": 1,
        "signal_timestamp_utc": data.loc[0, "timestamp_utc"], "market_open": 101.0,
        "execution_price": 101.0505, "slippage_bps": 5.0, "gross_notional": 101.0505,
        "commission": 0.05052525, "net_cash_flow": -101.10102525,
    }])
    manifest = {
        "strategy_config_hash": "config-hash", "data_hash": "data-hash", "code_commit": "abc",
        "provider": "Futu_LOCAL_CACHE", "symbol": "SPY", "timeframe": "1d",
        "start_date": "2020-01-01", "end_date": "2024-12-31", "fill_timing": "next_bar",
        "commission_bps": 5.0, "slippage_bps": 5.0, "optimization_allowed": False,
        "benchmark": "buy_and_hold", "generated_at_utc": "2024-01-01T00:00:00+00:00",
    }
    return AuditContext(
        spec=spec,
        capability=check_capabilities(spec),
        data=data,
        equity=equity,
        trades=trades,
        strategy_metrics={"total_return": 0.001},
        benchmark_return=0.001,
        manifest=manifest,
        artifact_paths={},
    )
~~~

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/pipeline/test_backtest_audit.py -q
~~~
Expected: FAIL because backtest_audit.py does not exist.

- [ ] **Step 2: Implement the audit checks**

Implement audit_backtest in this order:

1. _check_capability returns the capability blocker immediately.
2. _check_data_quality calls data_quality.validate_ohlcv and records DATA_QUALITY_FAILURE.
3. _check_next_bar_fill parses both timestamps as UTC and requires every fill timestamp to be strictly after its signal timestamp.
4. _check_costs compares each trade commission and slippage field with configured basis points using a floating-point tolerance.
5. _check_benchmark requires the manifest benchmark symbol, dates, commission and slippage to match StrategySpec and requires benchmark_return.
6. _check_optimization requires both StrategySpec and manifest optimization_allowed to be false.
7. _check_manifest requires strategy_config_hash, data_hash, code_commit, fill_timing, commission_bps, slippage_bps, and generated_at_utc.
8. _check_artifacts requires summary, equity, trades, manifest, and audit paths to exist when present.
9. _check_sample_and_concentration adds NO_TRADES for zero fills, SINGLE_TRADE_DOMINANCE when one closed trade contributes at least 80 percent of closed-trade absolute PnL, and ANNUAL_RETURN_CONCENTRATION when one calendar year contributes at least 80 percent of positive equity growth.
10. _check_reproducibility requires non-empty input hashes and compares current data hash with manifest data_hash.

Use these issue codes exactly: SAME_BAR_SIGNAL_FILL, COST_MISMATCH, DATA_QUALITY_FAILURE, NO_TRADES, SINGLE_TRADE_DOMINANCE, ANNUAL_RETURN_CONCENTRATION, MISSING_MANIFEST_FIELD, MISSING_ARTIFACT, HASH_MISMATCH, BENCHMARK_MISMATCH, OPTIMIZATION_ENABLED. Error issues yield FAIL; warnings without errors yield CONDITIONAL_PASS; no issues yield PASS. Capability blockers take precedence.

- [ ] **Step 3: Write audit references**

checks.md must list each check, required evidence, and issue code. statuses.md must define:

- PASS: formal baseline report allowed; no live-trading permission.
- CONDITIONAL_PASS: conditional report allowed; no optimization, promotion, or OOS pass claim.
- FAIL: stop formal conclusion.
- STRATEGY_CAPABILITY_BLOCKER: stop before data/backtest when produced by capability check.
- DATA_CAPABILITY_BLOCKER: stop before backtest when produced by data selection.

- [ ] **Step 4: Run focused and core tests**

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/pipeline/test_backtest_audit.py -q
python -m pytest tests/test_strategy.py tests/test_metrics.py tests/test_data_quality.py -q -p no:cacheprovider
~~~
Expected: audit tests and existing core tests pass.

- [ ] **Step 5: Commit**

Run:
~~~text
git add src/tv_quant/backtest_audit.py .agents/skills/quant-backtest-audit/SKILL.md .agents/skills/quant-backtest-audit/references/checks.md .agents/skills/quant-backtest-audit/references/statuses.md tests/pipeline/test_backtest_audit.py
git commit -m "Add deterministic backtest audit"
~~~
Expected: one commit containing Task 5 files.

---

## Task 6: Research Pipeline Orchestration

**Files:**
- Create: src/tv_quant/research_pipeline.py
- Create: src/tv_quant/run_manifest.py
- Create: .agents/skills/quant-research-pipeline/references/stages.md
- Create: .agents/skills/quant-research-pipeline/references/run-record.md
- Modify: .agents/skills/quant-research-pipeline/SKILL.md
- Create: tests/pipeline/test_research_pipeline.py
- Create: tests/pipeline/test_run_manifest.py

**Interfaces:**
- Consumes: load_strategy_spec, check_capabilities, load_standardized_csv, run_backtest, calculate_metrics, buy_and_hold_return, write_reports, and audit_backtest.
- Produces: build_manifest(...) -> dict[str, object] and run_pipeline(config_path: Path, options: PipelineOptions, refresh_data: Callable | None = None) -> PipelineResult.

Define these types at the top of src/tv_quant/research_pipeline.py:

~~~python
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from .pipeline_models import AuditReport, StrategySpec


@dataclass(frozen=True)
class PipelineOptions:
    data_root: Path = Path("data/raw")
    report_root: Path = Path("reports/runs")
    run_directory: Path | None = None
    quick: bool = False
    audit_only: bool = False
    skip_data_refresh: bool = False
    allow_smoke_test_data: bool = False


@dataclass(frozen=True)
class PipelineResult:
    status: str
    run_directory: Path | None
    audit_report: AuditReport | None
    warnings: tuple[str, ...]


RefreshData = Callable[[StrategySpec, Path], None]
~~~

- [ ] **Step 1: Write stage-order tests**

Create tests/pipeline/test_research_pipeline.py with deterministic temporary CSV helpers and these tests:

Import the helpers created in Task 2:

~~~python
from tests.pipeline.helpers import (
    write_ema_config,
    write_invalid_csv,
    write_rsi_config,
    write_valid_spy_csv,
)
~~~

The same test module defines the deterministic failed_audit helper before the tests:

~~~python
from tv_quant.pipeline_models import AuditIssue, AuditReport, AuditStatus


def failed_audit():
    return AuditReport(
        status=AuditStatus.FAIL,
        checks={"forced_failure": False},
        issues=(AuditIssue("FORCED_FAILURE", "ERROR", "test failure"),),
        warnings=(),
    )
~~~

~~~python
def test_capability_blocker_prevents_refresh_and_backtest(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("tv_quant.research_pipeline.run_backtest", lambda *a, **k: calls.append("backtest"))
    result = run_pipeline(
        write_rsi_config(tmp_path),
        PipelineOptions(data_root=tmp_path),
        refresh_data=lambda *a: calls.append("refresh"),
    )
    assert result.status == "STRATEGY_CAPABILITY_BLOCKER"
    assert calls == []


def test_existing_valid_cache_is_not_refreshed(monkeypatch, tmp_path):
    calls = []
    write_valid_spy_csv(tmp_path / "SPY_daily.csv")
    result = run_pipeline(
        write_ema_config(tmp_path),
        PipelineOptions(data_root=tmp_path, report_root=tmp_path / "reports"),
        refresh_data=lambda *a: calls.append("refresh"),
    )
    assert calls == []
    assert result.status in {"PASS", "CONDITIONAL_PASS"}


def test_data_quality_failure_prevents_backtest(monkeypatch, tmp_path):
    write_invalid_csv(tmp_path / "SPY_daily.csv")
    calls = []
    monkeypatch.setattr("tv_quant.research_pipeline.run_backtest", lambda *a, **k: calls.append("backtest"))
    result = run_pipeline(
        write_ema_config(tmp_path),
        PipelineOptions(data_root=tmp_path),
        refresh_data=lambda *a: None,
    )
    assert result.status in {"FAIL", "DATA_CAPABILITY_BLOCKER"}
    assert calls == []


def test_audit_failure_prevents_success(monkeypatch, tmp_path):
    write_valid_spy_csv(tmp_path / "SPY_daily.csv")
    monkeypatch.setattr("tv_quant.research_pipeline.audit_backtest", lambda context: failed_audit())
    result = run_pipeline(
        write_ema_config(tmp_path),
        PipelineOptions(data_root=tmp_path, report_root=tmp_path / "reports"),
        refresh_data=lambda *a: None,
    )
    assert result.status == "FAIL"
~~~

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/pipeline/test_research_pipeline.py -q
~~~
Expected: FAIL because the orchestrator does not exist.

- [ ] **Step 2: Implement cache-first data selection**

Implement _select_data(spec, options, refresh_data) in this order:

1. Select data_root / f"{spec.symbol}_daily.csv".
2. If the file exists, call load_standardized_csv once.
3. Require exact ticker, UTC daily timestamps, and coverage of start_date through end_date.
4. If valid and complete, filter to the configured range and do not call refresh_data.
5. If missing or incomplete and skip_data_refresh is true, return DATA_CAPABILITY_BLOCKER.
6. If missing or incomplete and refresh_data is absent, return DATA_CAPABILITY_BLOCKER.
7. Otherwise call refresh_data once, reload, and revalidate.
8. Use source label Futu_LOCAL_CACHE for validated_local_cache_first.
9. Use source label SMOKE_TEST_DATA_ONLY only when allow_smoke_test_data is true and data_source is yfinance.

DataQualityError stops before run_backtest. Do not call update_futu_csv from this module; Task 7 owns the refresh callback.

- [ ] **Step 3: Implement the fixed stages**

Before run_pipeline, create the minimal run_manifest.py interface required by this Task: canonical_hash(value), sha256_file(path), build_manifest(spec, data_path, source_label, artifact_paths, code_commit, smoke_test_marker), and write_manifest(path, manifest). Use the deterministic implementation specified in Task 8 Step 2, and add its hash tests to tests/pipeline/test_run_manifest.py before running the pipeline tests.

Define current_git_revision() in research_pipeline.py at the same time using the subprocess implementation specified in Task 8 Step 3, so Task 6 has no dependency on a later undefined function.

Implement run_pipeline in this exact order:

~~~python
def run_pipeline(config_path, options, refresh_data=None):
    spec = load_strategy_spec(config_path)
    capability = check_capabilities(
        spec,
        allow_smoke_test_data=options.allow_smoke_test_data,
    )
    if capability.status.value != "SUPPORTED":
        return PipelineResult(capability.status.value, None, None, capability.reasons)

    data_result = _select_data(spec, options, refresh_data)
    if isinstance(data_result, PipelineResult):
        return data_result
    data, data_path, source_label, data_warnings = data_result

    backtest = run_backtest(
        data,
        initial_cash=spec.initial_capital,
        commission_bps=spec.commission_bps,
        slippage_bps=spec.slippage_bps,
    )
    metrics = calculate_metrics(backtest.equity, backtest.trades, spec.initial_capital)
    benchmark = buy_and_hold_return(
        data,
        spec.initial_capital,
        spec.commission_bps,
        spec.slippage_bps,
    )
    summary = _build_summary(spec, metrics, benchmark, data_warnings + backtest.warnings, source_label)
    paths = write_reports(options.report_root, summary, backtest.equity, backtest.trades)
    code_commit = current_git_revision()
    smoke_test_marker = "SMOKE_TEST_DATA_ONLY" if source_label == "SMOKE_TEST_DATA_ONLY" else None
    manifest = build_manifest(
        spec, data_path, source_label, paths, code_commit, smoke_test_marker
    )
    manifest_path = paths["summary"].parent / "run_manifest.json"
    write_manifest(manifest_path, manifest)
    context = _build_audit_context(
        spec, capability, data, backtest, metrics, benchmark,
        manifest, paths, manifest_path,
    )
    audit = audit_backtest(context)
    _write_audit_and_update_summary(paths["summary"], paths["summary"].parent / "audit.json", audit)
    return PipelineResult(audit.status.value, paths["summary"].parent, audit, tuple(data_warnings))
~~~

Define _build_summary, _build_audit_context, _write_audit_and_update_summary, and _select_data in the same module before use. Preserve current summary keys ticker, data_start_utc, data_end_utc, parameters, total_return, cagr, max_drawdown, sharpe_ratio, trade_count, win_rate, buy_and_hold_return, strategy_minus_buy_hold, buy_and_hold_comparison, and validation_warnings.

- [ ] **Step 4: Implement audit-only behavior**

When audit_only is true:

- require run_directory;
- read summary.json, equity.csv, trades.csv, run_manifest.json, and audit.json;
- load manifest data_path and verify it exists and its hash matches;
- do not call refresh_data, run_backtest, calculate_metrics, or buy_and_hold_return;
- rerun audit_backtest and write only audit.json;
- return the new status and the same run directory.

Add a test that monkeypatches all calculation functions to raise AssertionError and verifies audit-only does not call them.

- [ ] **Step 5: Document stages and run records**

Write stages.md with the eight external steps: Parse and normalize, Capability check, Select data, Validate data, Run unoptimized backtest, Run Buy and Hold benchmark, Run audit, and Write Chinese report.

Write run-record.md with strategy config, assumptions, provider, symbol, timeframe, date range, data hash, config hash, code commit, fill timing, commission, slippage, strategy metrics, Buy and Hold metrics, audit status, warnings, and smoke-test marker.

Update the Skill body to state that it never skips data validation, never defaults to optimization, never invokes an order path, and never silently downloads duplicate cache data.

- [ ] **Step 6: Run focused tests and commit**

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/pipeline/test_research_pipeline.py tests/pipeline/test_backtest_audit.py -q
python -m pytest tests/test_strategy.py tests/test_metrics.py tests/test_data_quality.py -q -p no:cacheprovider
~~~
Expected: all pipeline and existing core tests pass.

Commit:
~~~text
git add src/tv_quant/research_pipeline.py .agents/skills/quant-research-pipeline/SKILL.md .agents/skills/quant-research-pipeline/references/stages.md .agents/skills/quant-research-pipeline/references/run-record.md tests/pipeline/test_research_pipeline.py
git commit -m "Add quant research pipeline orchestration"

## Task 7: PowerShell One-Click Entry

**Files:**
- Create: src/tv_quant/pipeline_cli.py
- Create: scripts/quant/run_pipeline.ps1
- Create: tests/pipeline/test_pipeline_cli.py
- Create: tests/pipeline/test_run_pipeline_script.py

**Interfaces:**
- Consumes: research_pipeline.run_pipeline and existing tv_quant.cli.main for explicit data refresh.
- Produces: python -m tv_quant.pipeline_cli and a Windows-safe script with controlled exit codes.

- [ ] **Step 1: Write CLI and script tests**

Create tests/pipeline/test_pipeline_cli.py:

~~~python
from tv_quant.pipeline_cli import exit_code_for_status


def test_success_statuses_return_zero():
    assert exit_code_for_status("PASS") == 0
    assert exit_code_for_status("CONDITIONAL_PASS") == 0


def test_blockers_and_failures_return_nonzero():
    assert exit_code_for_status("STRATEGY_CAPABILITY_BLOCKER") == 3
    assert exit_code_for_status("DATA_CAPABILITY_BLOCKER") == 4
    assert exit_code_for_status("FAIL") == 5
~~~

Create tests/pipeline/test_run_pipeline_script.py:

~~~python
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "quant" / "run_pipeline.ps1"


def test_script_has_required_switches_and_no_install_or_order_path():
    text = SCRIPT.read_text(encoding="utf-8")
    for token in ("$StrategyConfig", "$Quick", "$AuditOnly", "$SkipDataRefresh"):
        assert token in text
    assert "pip install" not in text.lower()
    assert "submit_order" not in text.lower()
    assert "place_order" not in text.lower()
    assert "OpenQuoteContext" not in text
~~~

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/pipeline/test_pipeline_cli.py tests/pipeline/test_run_pipeline_script.py -q
~~~
Expected: FAIL because the two files do not exist.

- [ ] **Step 2: Implement pipeline_cli.py**

Create these exact functions:

~~~python
import argparse
from pathlib import Path

from . import cli as legacy_cli
from .research_pipeline import PipelineOptions, run_pipeline
from .strategy_spec import load_strategy_spec


def exit_code_for_status(status: str) -> int:
    return {
        "PASS": 0,
        "CONDITIONAL_PASS": 0,
        "STRATEGY_CAPABILITY_BLOCKER": 3,
        "DATA_CAPABILITY_BLOCKER": 4,
        "FAIL": 5,
    }.get(status, 5)


def _refresh_data(spec, data_root: Path) -> None:
    source = "yfinance" if spec.data_source == "yfinance" else "futu"
    argv = [
        "download",
        "--tickers", spec.symbol,
        "--source", source,
        "--start", spec.start_date.isoformat(),
        "--end", spec.end_date.isoformat(),
        "--out-dir", str(data_root),
    ]
    if source == "yfinance":
        argv.append("--overwrite")
    result = legacy_cli.main(argv)
    if result != 0:
        raise RuntimeError(f"data refresh failed with exit code {result}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tv_quant.pipeline")
    parser.add_argument("--strategy-config", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data/raw"))
    parser.add_argument("--report-root", type=Path, default=Path("reports/runs"))
    parser.add_argument("--run-directory", type=Path)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--skip-data-refresh", action="store_true")
    parser.add_argument("--smoke-test-data", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        spec = load_strategy_spec(args.strategy_config)
        options = PipelineOptions(
            data_root=args.data_root,
            report_root=args.report_root,
            run_directory=args.run_directory,
            quick=args.quick,
            audit_only=args.audit_only,
            skip_data_refresh=args.skip_data_refresh,
            allow_smoke_test_data=args.smoke_test_data,
        )
        refresh = None if args.skip_data_refresh else _refresh_data
        result = run_pipeline(args.strategy_config, options, refresh_data=refresh)
    except (OSError, ValueError) as error:
        print(f"configuration_error={error}")
        return 2
    print(f"status={result.status}")
    if result.run_directory is not None:
        print(f"report_directory={result.run_directory}")
    return exit_code_for_status(result.status)


if __name__ == "__main__":
    raise SystemExit(main())
~~~

The implementation must not convert a blocker to success and must not catch a blocker as a generic configuration error.

- [ ] **Step 3: Implement run_pipeline.ps1**

Create scripts/quant/run_pipeline.ps1:

~~~powershell
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$StrategyConfig,
    [switch]$Quick,
    [switch]$AuditOnly,
    [switch]$SkipDataRefresh,
    [switch]$SmokeTestData,
    [string]$DataRoot = "data/raw",
    [string]$ReportRoot = "reports/runs",
    [string]$RunDirectory
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location -LiteralPath $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $pythonCommand = Get-Command python -ErrorAction Stop
    $python = $pythonCommand.Source
}

$arguments = @(
    "-m", "tv_quant.pipeline_cli",
    "--strategy-config", $StrategyConfig,
    "--data-root", $DataRoot,
    "--report-root", $ReportRoot
)
if ($Quick) { $arguments += "--quick" }
if ($AuditOnly) { $arguments += "--audit-only" }
if ($SkipDataRefresh) { $arguments += "--skip-data-refresh" }
if ($SmokeTestData) { $arguments += "--smoke-test-data" }
if ($RunDirectory) { $arguments += @("--run-directory", $RunDirectory) }

$env:PYTHONPATH = Join-Path $root "src"
& $python @arguments
exit $LASTEXITCODE
~~~

The script must not create .venv, run pip, install dependencies, call Futu directly, or contain an order API. Its argument array must preserve paths containing spaces.

- [ ] **Step 4: Run focused tests and commit**

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/pipeline/test_pipeline_cli.py tests/pipeline/test_run_pipeline_script.py -q
~~~
Expected: all focused tests pass.

Commit:
~~~text
git add src/tv_quant/pipeline_cli.py scripts/quant/run_pipeline.ps1 tests/pipeline/test_pipeline_cli.py tests/pipeline/test_run_pipeline_script.py
git commit -m "Add PowerShell pipeline entry"
~~~

---

## Task 8: Run Manifest and Report Binding

**Files:**
- Modify: src/tv_quant/run_manifest.py: report binding fields only; preserve Task 6 hash behavior
- Modify: tests/pipeline/test_run_manifest.py: add report binding assertions
- Modify: src/tv_quant/research_pipeline.py: manifest and report calls

**Interfaces:**
- Consumes: the deterministic run_manifest.py interface created in Task 6, StrategySpec, data path, source label, existing report paths, PipelineOptions, and current Git revision.
- Produces: report-bound run_manifest.json/audit.json in each run directory without a second result writer.

- [ ] **Step 1: Write hash and manifest tests**

Extend tests/pipeline/test_run_manifest.py with these regression assertions:

~~~python
from tests.pipeline.helpers import valid_payload
from tv_quant.strategy_spec import validate_strategy_mapping
from tv_quant.run_manifest import build_manifest, canonical_hash, sha256_file


def valid_spec():
    return validate_strategy_mapping(valid_payload())


def test_same_payload_has_same_hash():
    payload = {"symbol": "SPY", "fill_timing": "next_bar"}
    assert canonical_hash(payload) == canonical_hash({"fill_timing": "next_bar", "symbol": "SPY"})


def test_file_hash_changes_when_content_changes(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("close,100\n", encoding="utf-8")
    first = sha256_file(path)
    path.write_text("close,101\n", encoding="utf-8")
    assert sha256_file(path) != first


def test_manifest_contains_required_run_fields(tmp_path):
    data = tmp_path / "SPY_daily.csv"
    data.write_text("data", encoding="utf-8")
    manifest = build_manifest(
        spec=valid_spec(),
        data_path=data,
        source_label="Futu_LOCAL_CACHE",
        artifact_paths={},
        code_commit="abc123",
        smoke_test_marker=None,
    )
    for field in (
        "strategy_config_hash", "data_hash", "code_commit", "symbol",
        "timeframe", "fill_timing", "commission_bps", "slippage_bps",
        "optimization_allowed", "generated_at_utc",
    ):
        assert field in manifest
~~~

Define valid_spec by calling validate_strategy_mapping(valid_payload()) from Task 2. Keep the hash tests created in Task 6 unchanged.

- [ ] **Step 2: Preserve deterministic hashing and extend the manifest fields**

Do not replace the Task 6 implementation. Confirm that src/tv_quant/run_manifest.py still provides canonical_hash, sha256_file, build_manifest, and write_manifest with the exact signatures declared there. Add only report-bound fields required by the pipeline, including artifact_paths, provider, benchmark, and smoke_test_marker.

~~~python
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    spec,
    data_path,
    source_label,
    artifact_paths,
    code_commit,
    smoke_test_marker,
):
    return {
        "strategy_config_hash": canonical_hash(spec.raw),
        "data_hash": sha256_file(data_path),
        "code_commit": code_commit,
        "strategy_name": spec.strategy_name,
        "provider": source_label,
        "symbol": spec.symbol,
        "timeframe": spec.timeframe,
        "start_date": spec.start_date.isoformat(),
        "end_date": spec.end_date.isoformat(),
        "fill_timing": spec.fill_timing,
        "commission_bps": spec.commission_bps,
        "slippage_bps": spec.slippage_bps,
        "optimization_allowed": spec.optimization_allowed,
        "benchmark": spec.benchmark,
        "data_path": str(data_path),
        "artifact_paths": {name: str(path) for name, path in artifact_paths.items()},
        "smoke_test_marker": smoke_test_marker,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
~~~

Add write_manifest using UTF-8 JSON with sorted keys and two-space indentation.

- [ ] **Step 3: Bind manifest and audit to existing reports**

Update research_pipeline.py so write_reports remains the only producer of summary.json, equity.csv, and trades.csv. After it returns paths:

1. obtain code_commit from git rev-parse HEAD through current_git_revision() defined as a small read-only subprocess helper;
2. calculate and write run_manifest.json;
3. audit with manifest and artifact paths;
4. write audit.json;
5. update summary.json only with audit_status, provider, smoke_test_marker, strategy_config_hash, data_hash, and audit_issues.

Do not create a second equity or trades writer and do not change reporting.py.

Define the helper before its first call:

~~~python
import subprocess


def current_git_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
~~~

- [ ] **Step 4: Run tests and commit**

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/pipeline/test_run_manifest.py tests/pipeline/test_research_pipeline.py -q
python -m pytest tests/test_metrics.py -q -p no:cacheprovider
~~~
Expected: hash, manifest, pipeline, and existing report tests pass.

Commit:
~~~text
git add src/tv_quant/run_manifest.py src/tv_quant/research_pipeline.py tests/pipeline/test_run_manifest.py
git commit -m "Bind pipeline runs to deterministic manifests"
~~~

---

## Task 9: Minimal AGENTS.md Entry and User Routing

**Files:**
- Modify: AGENTS.md
- Modify: .agents/skills/quant-research-pipeline/SKILL.md
- Create: tests/skills/test_agents_entry.py

**Interfaces:**
- Consumes: the three project Skill names and the safety rules already present in AGENTS.md.
- Produces: a short routing rule; detailed behavior remains in Skill references.

- [ ] **Step 1: Write the routing test**

Create tests/skills/test_agents_entry.py:

~~~python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_agents_routes_quant_research_to_pipeline():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "quant-research-pipeline" in text
    assert "optimization_allowed" in text
    assert "STRATEGY_CAPABILITY_BLOCKER" in text
    assert "不自动下单" in text or "不发送订单" in text
    assert "正式结果必须经过审计" in text
~~~

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/skills/test_agents_entry.py -q
~~~
Expected: FAIL because the routing block is absent.

- [ ] **Step 2: Append the minimal routing block**

Append this exact block to AGENTS.md without rewriting existing sections:

~~~markdown
## Quant Research Pipeline Entry

- 策略生成和回测任务优先调用 quant-research-pipeline。
- 默认生成中文报告，optimization_allowed=false，fill_timing=next_bar，并比较对应标的 Buy and Hold。
- 正式数据优先使用 validated local cache；yfinance 只用于明确标记的 smoke test。
- 不支持策略必须返回 STRATEGY_CAPABILITY_BLOCKER；数据不可用必须返回 DATA_CAPABILITY_BLOCKER。
- 正式结果必须经过 quant-backtest-audit；当前阶段不自动下单、不连接实盘账户。
~~~

Update quant-research-pipeline/SKILL.md to reference AGENTS.md for routing while keeping detailed stages in references/stages.md.

- [ ] **Step 3: Run tests and commit**

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/skills/test_agents_entry.py tests/skills/test_skill_contracts.py -q
~~~
Expected: all routing tests pass.

Commit:
~~~text
git add AGENTS.md .agents/skills/quant-research-pipeline/SKILL.md tests/skills/test_agents_entry.py
git commit -m "Route quant research tasks through pipeline"

## Task 10: Controlled EMA Acceptance and RSI Blocker

**Files:**
- Create: tests/pipeline/test_ema_acceptance.py
- Modify: config/strategies/ema_baseline.yaml only when a schema test identifies a field mismatch
- Modify: src/tv_quant/research_pipeline.py only when its defined interface fails the offline fixture
- Do not modify: src/tv_quant/strategy.py, src/tv_quant/metrics.py, src/tv_quant/data_quality.py, src/tv_quant/reporting.py

**Interfaces:**
- Consumes: ema_baseline.yaml, deterministic SPY daily fixture, local-cache-first selection, existing EMA functions, and audit.
- Produces: PASS or CONDITIONAL_PASS for supported EMA and STRATEGY_CAPABILITY_BLOCKER for RSI without refresh or backtest.

- [ ] **Step 1: Write the offline acceptance tests**

Create tests/pipeline/test_ema_acceptance.py with a deterministic fixture generator using the same 203-bar crossover shape as tests/test_strategy.py. The test writes SPY_daily.csv below tmp_path, writes an EMA YAML below tmp_path, and passes tmp_path as data_root.

Import write_crossover_csv, write_ema_config, and write_rsi_config from tests.pipeline.helpers; the helper functions define the complete deterministic fixture used by this acceptance test.

The test module also imports json, tv_quant.research_pipeline.PipelineOptions, and tv_quant.research_pipeline.run_pipeline.

~~~python
def test_ema_pipeline_writes_report_and_audit(tmp_path):
    write_crossover_csv(tmp_path / "SPY_daily.csv")
    config = write_ema_config(tmp_path)
    result = run_pipeline(
        config,
        PipelineOptions(
            data_root=tmp_path,
            report_root=tmp_path / "reports",
            skip_data_refresh=True,
        ),
    )
    assert result.status in {"PASS", "CONDITIONAL_PASS"}
    assert (result.run_directory / "summary.json").is_file()
    assert (result.run_directory / "equity.csv").is_file()
    assert (result.run_directory / "trades.csv").is_file()
    assert (result.run_directory / "run_manifest.json").is_file()
    assert (result.run_directory / "audit.json").is_file()
    summary = json.loads(
        (result.run_directory / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["buy_and_hold_return"] is not None
    assert summary["parameters"]["ema_fast"] == 50
    assert summary["parameters"]["ema_slow"] == 200
    assert summary["audit_status"] in {"PASS", "CONDITIONAL_PASS"}


def test_rsi_blocker_does_not_refresh_or_backtest(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "tv_quant.research_pipeline.run_backtest",
        lambda *a, **k: calls.append("backtest"),
    )
    result = run_pipeline(
        write_rsi_config(tmp_path),
        PipelineOptions(data_root=tmp_path),
        refresh_data=lambda *a: calls.append("refresh"),
    )
    assert result.status == "STRATEGY_CAPABILITY_BLOCKER"
    assert calls == []
~~~

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/pipeline/test_ema_acceptance.py -q
~~~
Expected: FAIL until the full pipeline is connected.

- [ ] **Step 2: Enforce the controlled data policy**

The acceptance test never uses network data. An operator smoke command may use an existing data/raw/SPY_daily.csv with SkipDataRefresh. If the cache is absent, it returns DATA_CAPABILITY_BLOCKER rather than downloading. An explicitly labeled yfinance run may use SmokeTestData and must never be reported as a formal result.

- [ ] **Step 3: Run acceptance and regression tests**

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/pipeline/test_ema_acceptance.py tests/pipeline/test_strategy_spec.py tests/pipeline/test_backtest_audit.py tests/pipeline/test_research_pipeline.py -q
python -m pytest tests -q -p no:cacheprovider
~~~
Expected: all new and existing tests pass. No Futu OpenD, network download, order API, or real account is used.

- [ ] **Step 4: Commit**

Run:
~~~text
git add tests/pipeline/test_ema_acceptance.py
git commit -m "Add EMA pipeline acceptance coverage"
~~~
Expected: one commit containing the acceptance test only.

---

## Task 11: Final Phase 1 Verification

**Files:**
- Modify: none unless a previous task has an explicitly failing test with a correction declared in that task.
- Test: tests/skills, tests/pipeline, and existing tests.
- Verify: docs, scripts, configuration, and Git state.

**Interfaces:**
- Consumes: Task 1 through Task 10 deliverables.
- Produces: evidence that Phase 1 is complete or a precise failing task and status; it does not authorize Phase 2.

- [ ] **Step 1: Run the complete test suite**

Run:
~~~text
$env:PYTHONPATH = "src"
python -m pytest tests/skills tests/pipeline tests -q -p no:cacheprovider
~~~
Expected: all tests pass. If a test fails, record its exact node id and traceback, return to its owning Task, change only that Task's declared files, rerun its focused test, then repeat this command.

- [ ] **Step 2: Run the PowerShell syntax check**

Run:
~~~powershell
powershell.exe -NoProfile -Command "& { [scriptblock]::Create((Get-Content -Raw -LiteralPath 'scripts/quant/run_pipeline.ps1')) | Out-Null; Write-Output 'POWERSHELL_PARSE_OK' }"
~~~
Expected: POWERSHELL_PARSE_OK and no dependency installation or environment creation.

- [ ] **Step 3: Run the controlled offline pipeline**

Run:
~~~text
$env:PYTHONPATH = "src"
python -m tv_quant.pipeline_cli --strategy-config config/strategies/ema_baseline.yaml --data-root <temporary-data-root> --report-root <temporary-report-root> --skip-data-refresh
~~~
Expected with no cache: exit code 4 and DATA_CAPABILITY_BLOCKER. With a deterministic local SPY cache: exit code 0 and PASS or CONDITIONAL_PASS plus summary.json, equity.csv, trades.csv, run_manifest.json, and audit.json.

- [ ] **Step 4: Run repository integrity checks**

Run:
~~~text
git diff --check
git status --short
git diff --name-only HEAD~11..HEAD
~~~
Expected: no whitespace errors, no uncommitted implementation files, and only declared files in the task commit range. Do not push.

- [ ] **Step 5: Confirm the acceptance matrix**

Record these evidence links in the implementation handoff:

| Acceptance item | Evidence |
|---|---|
| Three project Skills discoverable | tests/skills/test_skill_contracts.py |
| YAML config valid | tests/pipeline/test_strategy_spec.py |
| Capability matrix fixed | tests/pipeline/test_capabilities.py |
| RSI blocked before data/backtest | tests/pipeline/test_ema_acceptance.py |
| Stage order and stop rules | tests/pipeline/test_research_pipeline.py |
| Five-state audit | tests/pipeline/test_backtest_audit.py |
| Hashes and run record | tests/pipeline/test_run_manifest.py |
| PowerShell parameters and exit codes | tests/pipeline/test_pipeline_cli.py and tests/pipeline/test_run_pipeline_script.py |
| Existing baseline preserved | tests/test_strategy.py, tests/test_metrics.py, tests/test_data_quality.py |
| No automatic trading | Skill/script static tests and absence of order API |
| No Phase 2 capability | capability matrix and configuration tests |

- [ ] **Step 6: Commit only final verification changes**

Run `git diff --name-only` and inspect every changed path. If the verification exposed a defect, return to the owning Task, modify only that Task's declared files, run that Task's focused test, and use that Task's exact `git add` and commit command. If verification produced no correction, do not create an empty commit; record that the final verification commit was intentionally omitted.

Expected: only declared verification corrections are committed, with the owning Task's commit message. No implementation file is changed solely to manufacture a final commit.

---

## Task Commit Order

Use these exact commit messages and keep each commit reviewable:

1. Add quant research Skill contracts
2. Add strategy configuration contract
3. Add strategy capability blockers
4. Define quant strategy specification Skill
5. Add deterministic backtest audit
6. Add quant research pipeline orchestration
7. Add PowerShell pipeline entry
8. Bind pipeline runs to deterministic manifests
9. Route quant research tasks through pipeline
10. Add EMA pipeline acceptance coverage
11. Complete quant research pipeline verification

No task may push remote, create a PR, modify user-level Skills, or enter Phase 2.

## Design Coverage Matrix

| Design requirement | Planned task |
|---|---|
| Three first-phase project Skills | Tasks 1 and 4 |
| Natural-language strategy standardization | Tasks 2 and 4 |
| Existing Futu local cache and yfinance boundary | Tasks 3, 6, 7, and 10 |
| Fixed EMA baseline integration | Tasks 2, 6, and 10 |
| Fixed eight-stage pipeline | Task 6 |
| Audit checks and five statuses | Task 5 |
| Capability blockers before data/backtest | Tasks 3 and 6 |
| Buy and Hold fairness | Tasks 5, 6, and 10 |
| Configuration/data/code hashes | Task 8 |
| Token control and concise reports | Skill references in Tasks 4 and 6 |
| User-level Skill isolation | Tasks 1, 4, and 9 |
| No auto-trading or external execution | All Skill tests and Task 7 |
| Tests and rollback | Tasks 1 through 11 |
| Locked OOS and Walk-forward boundaries | Global Constraints and references in Tasks 5 and 6 |
| No VectorBT or options in Phase 1 | Global Constraints and Task 3 matrix |
| AGENTS.md routing | Task 9 |
| Second-phase entry gate | Task 11 acceptance handoff |

## Plan Self-Review

Before implementing any task, the plan reviewer must:

1. Compare every section of docs/superpowers/specs/2026-07-24-quant-skills-pipeline-design.md with the Design Coverage Matrix.
2. Confirm every path in Planned File Map is exact and no existing core module is duplicated.
3. Confirm all names used by later tasks were defined in Shared Interfaces or the owning earlier Task.
4. Run a repository search for forbidden placeholder words and require zero matches.
5. Run git diff --check on the plan commit.
6. Confirm the plan does not authorize installation, network download, Futu OpenD, real trading, remote push, PR creation, or Phase 2 work.
7. Confirm that each Task has a failing test, concrete implementation content, a focused test command, a regression command, and an exact commit message.

Execution handoff: this document is a plan only. Implementers must choose either subagent-driven development or executing-plans after separate implementation approval. No implementation begins from this plan alone.

~~~

~~~

~~~
