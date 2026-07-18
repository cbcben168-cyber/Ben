# Phase 1 Data Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a trustworthy, deterministic, auditable Phase 1 data foundation that converts unadjusted Futu 30-minute US bars into validated RTH 30-minute, strict 60-minute research, and same-source daily datasets with immutable manifests.

**Architecture:** Keep the existing `tv_quant.cli` daily EMA baseline operational and untouched. Add an isolated `tv_quant.phase1_data` package whose provider adapters feed immutable typed records through calendar normalization, session and OHLCV quality gates, corporate-action adjustment, aggregation, manifest construction, and an atomic versioned publisher. The new CLI is invoked only as `python -m tv_quant.phase1_data.cli`, publishes only under `data/phase1/datasets/<dataset_id>/`, and never falls back from Futu to yfinance or the legacy daily pipeline.

**Tech Stack:** Python 3.12, pandas 3.0.3, NumPy 2.5.1, pytest 9.1.1, Futu API 10.9.x, `exchange-calendars==4.13.2`, `zoneinfo`, dataclasses, pathlib, hashlib, JSON, CSV.

**Primary implementation references:** [`exchange-calendars` 4.13.2 on PyPI](https://pypi.org/project/exchange_calendars/), [Futu historical candlestick API](https://openapi.futunn.com/futu-api-doc/en/quote/request-history-kline.html), and [Futu adjustment-factor API](https://openapi.futunn.com/futu-api-doc/en/quote/get-rehab.html). These references define dependency/API vocabulary; the frozen design and checked fixtures define system behavior.

## Global Constraints

- Authoritative design baseline: commit `28a234d` and `docs/superpowers/specs/2026-07-18-quant-swing-research-system-design.md`.
- Scope is Implementation Phase 1 only: schemas, XNYS calendar, 30-minute Futu RTH data for `QQQ`, `SPY`, `IWM`, `RSP`, and `DIA`, raw/research fields, corporate actions, daily and strict 60-minute aggregation, Data Manifest, hashing, publication, and isolated CLI.
- Phase 2 and later strategy logic is excluded: EMA, ATR, volatility, pivot, pullback, recovery, entries, exits, stops, positions, costs, performance metrics, parameter search, Walk-forward, Locked OOS, external ETF validation, TradingView, options, portfolio logic, paper trading, and live trading.
- Internal instants are timezone-aware UTC; session rules are calculated in `America/New_York` with XNYS. Fixed UTC offsets are prohibited.
- An ordinary complete XNYS session contains 13 half-hour bars beginning 09:30 through 15:30 local. An early close uses `(session_close - session_open) / 30 minutes`; 09:30–13:00 contains 7 bars.
- Early-close sessions publish 30-minute and daily data but publish no 60-minute research bars; manifest policy is exactly `EXCLUDE_FROM_60M_SEQUENCE`.
- `TimeKeyFixtureKind` is exactly `TEST | PRODUCTION_CAPTURE`. Checked-in files below `tests/fixtures/phase1/` are always `TEST`; CSV/offline tests may use them, but a Futu build requires separately captured `PRODUCTION_CAPTURE` evidence. Setting `verified=true` never upgrades `TEST` evidence.
- `validate-time-key` validates evidence structure, SHA-256 syntax, and expected time conversion only; it never claims to prove Futu semantics. Real Futu semantic confirmation is a separate manual integration step.
- Internal `symbol` is the bare ETF symbol such as `QQQ`; supplier `provider_code` is separate, such as `US.QQQ`. They are never stored interchangeably.
- Futu 30-minute requests use `KLType.K_30M`, `AuType.NONE`, and no extended-hours request. Futu failure is explicit and cannot trigger another provider.
- Futu's documented `split_ratio` is vendor-oriented; the adapter converts it to the design contract `new_shares / old_shares` by `Decimal(1) / vendor_split_ratio`.
- Raw OHLCV is immutable. Research OHLC is divided by cumulative future verified split factors, research volume is multiplied by the same factors, and dividends never alter research fields.
- Every blocking data error produces `DATA_QUALITY_FAILED` or `DATA_ACTIONS_UNVERIFIED`, prevents publication, and returns a documented nonzero CLI exit code; expected calendar, contract, source-mixing, aggregation, and publication errors never escape as an uncaught traceback.
- Corporate-action content hash excludes `fetched_at_utc`; source-response hash is tracked separately; fetch time is audit metadata only and cannot change `dataset_id`.
- Before rename, the publisher parses staged `manifest.json`, validates schema and publishable statuses, verifies the exact declared file set, recomputes every file hash and dataset hash, recomputes `dataset_id`, and verifies that the destination directory name matches it.
- Dataset directories are immutable. A failed staging write or validation cannot replace an existing valid dataset.
- The legacy files `src/tv_quant/cli.py`, `src/tv_quant/downloader.py`, `src/tv_quant/futu_downloader.py`, `src/tv_quant/data_quality.py`, `src/tv_quant/strategy.py`, and existing tests remain unchanged.
- Each task follows red-green-refactor order, runs its focused tests, runs all existing tests, and creates one independent local commit.
- No API key, password, account information, `.env` content, broker connection, or order-sending code may be added.

---

## File Structure

### Existing files modified during implementation

- `requirements.txt`: add the exact XNYS calendar dependency `exchange-calendars==4.13.2`.
- `.gitignore`: ignore `data/phase1/staging/` and `data/phase1/datasets/` while retaining fixture data under `tests/fixtures/phase1/`.

### New production files

- `src/tv_quant/phase1_data/__init__.py`: export the stable Phase 1 public types and pure functions.
- `src/tv_quant/phase1_data/models.py`: enums and frozen dataclasses only.
- `src/tv_quant/phase1_data/errors.py`: Phase 1 exception hierarchy only.
- `src/tv_quant/phase1_data/calendar.py`: XNYS schedule lookup, local/UTC conversion, early-close detection, and schedule hashing.
- `src/tv_quant/phase1_data/providers.py`: `DataProvider` and quote-context protocols plus `CSVProvider`.
- `src/tv_quant/phase1_data/futu.py`: Futu pagination, K_30M raw-bar retrieval, rehab retrieval, time fixture loading, timestamp normalization, and supplier-to-design split conversion.
- `src/tv_quant/phase1_data/sessions.py`: RTH filtering and per-session 30-minute completeness validation.
- `src/tv_quant/phase1_data/quality.py`: raw/research OHLCV and split-factor validation.
- `src/tv_quant/phase1_data/corporate_actions.py`: canonical corporate-action content hash and split adjustment.
- `src/tv_quant/phase1_data/aggregation.py`: same-source daily aggregation and strict normal-session 60-minute aggregation.
- `src/tv_quant/phase1_data/manifest.py`: canonical dataset identity and `DataManifest` construction.
- `src/tv_quant/phase1_data/storage.py`: canonical serialization, SHA-256 helpers, staging validation, and atomic immutable publication.
- `src/tv_quant/phase1_data/pipeline.py`: deterministic orchestration and downstream quality gates.
- `src/tv_quant/phase1_data/cli.py`: isolated `validate-time-key` and `build` commands with fixed exit codes.

### New tests and fixtures

- `tests/phase1_data/test_models.py`
- `tests/phase1_data/helpers.py`
- `tests/phase1_data/test_calendar.py`
- `tests/phase1_data/test_futu.py`
- `tests/phase1_data/test_sessions.py`
- `tests/phase1_data/test_quality.py`
- `tests/phase1_data/test_corporate_actions.py`
- `tests/phase1_data/test_aggregation.py`
- `tests/phase1_data/test_manifest_storage.py`
- `tests/phase1_data/test_pipeline_cli.py`
- `tests/phase1_data/test_public_contract.py`
- `tests/phase1_data/test_phase1_acceptance.py`
- `tests/fixtures/phase1/futu_time_key_start.json`
- `tests/fixtures/phase1/futu_time_key_end.json`
- `tests/fixtures/phase1/futu_time_key_unverified.json`
- `tests/fixtures/phase1/normal_session_2024-11-27.csv`
- `tests/fixtures/phase1/early_close_2024-11-29.csv`
- `tests/fixtures/phase1/corporate_actions.json`
- `docs/phase1-data-contract.md`

### Runtime layout

```text
data/phase1/
├── evidence/
│   └── futu_time_key_<symbol>_<captured_at_utc>.json
├── staging/<run_id>/
│   └── <dataset_id>/
│       ├── bars_30m.csv
│       ├── bars_60m.csv
│       ├── daily.csv
│       ├── corporate_actions.json
│       └── manifest.json
└── datasets/<dataset_id>/
    ├── bars_30m.csv
    ├── bars_60m.csv
    ├── daily.csv
    ├── corporate_actions.json
    └── manifest.json
```

The legacy baseline continues to use `data/raw/<TICKER>_daily.csv`, `python -m tv_quant.cli download`, and `python -m tv_quant.cli backtest`. Phase 1 consumers receive an explicit immutable dataset directory and cannot pass a legacy daily CSV into the new pipeline.

## Frozen Public Interfaces

```python
class DataProvider(Protocol):
    source_name: str
    source_version: str
    def fetch_30m(self, symbol: str, start: date, end: date) -> pd.DataFrame: ...
    def fetch_corporate_actions(self, symbol: str, start: date, end: date) -> CorporateActionBatch: ...

class TradingCalendar(Protocol):
    library_name: str
    library_version: str
    def sessions(self, start: date, end: date) -> tuple[SessionSchedule, ...]: ...
    def session(self, session_date: date) -> SessionSchedule: ...
    def schedule_hash(self, start: date, end: date) -> str: ...

def load_time_key_fixture(path: str | Path) -> TimeKeyEvidence: ...
def require_futu_production_evidence(evidence: TimeKeyEvidence, symbol: str, provider_code: str) -> None: ...
def normalize_futu_timestamp(source_timestamp: str, semantics: TimeKeySemantics) -> NormalizedTimestamp: ...
def filter_rth_bars(bars: Sequence[Bar30mRecord], schedule: SessionSchedule) -> tuple[Bar30mRecord, ...]: ...
def validate_30m_session(bars: Sequence[Bar30mRecord], schedule: SessionSchedule) -> SessionValidationResult: ...
def validate_ohlcv(bars: Sequence[Bar30mRecord]) -> DataQualityResult: ...
def validate_split_factors(bars: Sequence[Bar30mRecord]) -> DataQualityResult: ...
def calculate_corporate_action_content_sha256(actions: Sequence[CorporateAction]) -> str: ...
def apply_split_adjustment(bars: Sequence[Bar30mRecord], actions: Sequence[CorporateAction]) -> tuple[Bar30mRecord, ...]: ...
def aggregate_daily_bars(bars: Sequence[Bar30mRecord]) -> tuple[DailyBarRecord, ...]: ...
def aggregate_60m_research_bars(bars: Sequence[Bar30mRecord], schedule: SessionSchedule) -> tuple[Bar60mRecord, ...]: ...
def build_data_manifest(request: ManifestRequest) -> DataManifest: ...
def calculate_file_sha256(path: str | Path) -> str: ...
def calculate_dataset_sha256(files: Mapping[str, bytes]) -> str: ...
def calculate_dataset_id(manifest_payload: Mapping[str, object]) -> str: ...
def atomic_write_dataset(destination: Path, files: Mapping[str, bytes]) -> Path: ...
```

## Task 1: Freeze schemas, enums, and error states

**Files:**
- Create: `src/tv_quant/phase1_data/__init__.py`
- Create: `src/tv_quant/phase1_data/models.py`
- Create: `src/tv_quant/phase1_data/errors.py`
- Create: `tests/phase1_data/test_models.py`

**Interfaces:**
- Consumes: Python standard-library `date`, `datetime`, `Decimal`, `Enum`, and frozen dataclasses.
- Produces: the five-symbol `PHASE1_SYMBOLS` allow-list; time-key evidence types; invariant-checking schedule/bar records; separate corporate-action content/source evidence; manifest requests/results; and the complete Phase 1 exception hierarchy.
- Deliberately defers public `__all__` exports to Task 10 so its first red test fails only on the public API/documentation contract, not on an unfinished pipeline.

- [ ] **Step 1: Write the failing schema tests**

```python
# tests/phase1_data/test_models.py
from dataclasses import FrozenInstanceError, fields
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from tv_quant.phase1_data.errors import DataContractError
from tv_quant.phase1_data.models import (
    PHASE1_SYMBOLS, Bar30mRecord, Bar60mRecord, CorporateAction, CorporateActionBatch,
    CorporateActionType, DataQualityResult, DataStatus, EarlyClose60mPolicy,
    NormalizedTimestamp, SessionSchedule, TimeKeyFixtureKind, TimeKeySemantics,
)

NY = ZoneInfo("America/New_York")


def valid_bar() -> Bar30mRecord:
    start_local = datetime(2024, 11, 27, 9, 30, tzinfo=NY)
    end_local = start_local + timedelta(minutes=30)
    return Bar30mRecord(
        "2024-11-27 09:30:00", start_local, end_local,
        start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc),
        date(2024, 11, 27), True, False, "FUTU", "QQQ", "US.QQQ",
        Decimal("500"), Decimal("502"), Decimal("499"), Decimal("501"),
        Decimal("1000"), Decimal("500"), Decimal("502"), Decimal("499"),
        Decimal("501"), Decimal("1000"), Decimal("1"),
    )


def test_bar30m_contract_is_frozen_and_contains_raw_and_research_fields():
    names = {field.name for field in fields(Bar30mRecord)}
    assert names == {
        "source_timestamp", "bar_start_local", "bar_end_local", "bar_start_utc",
        "bar_end_utc", "session_date", "is_regular_session", "is_early_close",
        "source", "symbol", "provider_code", "raw_open", "raw_high", "raw_low", "raw_close",
        "raw_volume", "research_open", "research_high", "research_low",
        "research_close", "research_volume", "split_factor_t",
    }
    bar = valid_bar()
    with pytest.raises(FrozenInstanceError):
        bar.raw_close = Decimal("0")


def test_exact_machine_states_symbols_and_split_definition_are_frozen():
    assert {state.value for state in DataStatus} == {
        "VALID", "DATA_QUALITY_FAILED", "DATA_ACTIONS_UNVERIFIED"
    }
    assert PHASE1_SYMBOLS == frozenset({"QQQ", "SPY", "IWM", "RSP", "DIA"})
    assert {kind.value for kind in TimeKeyFixtureKind} == {"TEST", "PRODUCTION_CAPTURE"}
    assert TimeKeySemantics.BAR_START.value == "BAR_START"
    assert TimeKeySemantics.BAR_END.value == "BAR_END"
    assert EarlyClose60mPolicy.EXCLUDE.value == "EXCLUDE_FROM_60M_SEQUENCE"
    action = CorporateAction(
        "FUTU", "QQQ", CorporateActionType.SPLIT, date(2022, 6, 6),
        Decimal("2"), datetime(2024, 1, 1, tzinfo=timezone.utc), "a" * 64, True,
    )
    assert action.ratio_new_over_old == Decimal("2")
    batch = CorporateActionBatch((action,), "b" * 64, action.fetched_at_utc, True)
    assert batch.source_sha256 == "b" * 64


@pytest.mark.parametrize(
    ("local_start", "utc_start"),
    [
        (datetime(2024, 3, 8, 9, 30, tzinfo=NY), datetime(2024, 3, 8, 14, 30, tzinfo=timezone.utc)),
        (datetime(2024, 3, 11, 9, 30, tzinfo=NY), datetime(2024, 3, 11, 13, 30, tzinfo=timezone.utc)),
    ],
)
def test_normalized_timestamp_accepts_dst_aware_matching_instants(local_start, utc_start):
    value = NormalizedTimestamp(
        "source", local_start, local_start + timedelta(minutes=30),
        utc_start, utc_start + timedelta(minutes=30),
    )
    assert value.bar_start_local.astimezone(timezone.utc) == value.bar_start_utc


def test_schedule_and_bars_reject_naive_mismatched_or_wrong_duration_times():
    with pytest.raises(DataContractError, match="timezone-aware"):
        NormalizedTimestamp(
            "source", datetime(2024, 11, 27, 9, 30), datetime(2024, 11, 27, 10),
            datetime(2024, 11, 27, 14, 30, tzinfo=timezone.utc),
            datetime(2024, 11, 27, 15, tzinfo=timezone.utc),
        )
    start = datetime(2024, 11, 27, 9, 30, tzinfo=NY)
    with pytest.raises(DataContractError, match="same instant"):
        NormalizedTimestamp(
            "source", start, start + timedelta(minutes=30),
            datetime(2024, 11, 27, 14, 31, tzinfo=timezone.utc),
            datetime(2024, 11, 27, 15, 1, tzinfo=timezone.utc),
        )
    with pytest.raises(DataContractError, match="30 minutes"):
        NormalizedTimestamp(
            "source", start, start + timedelta(minutes=29),
            start.astimezone(timezone.utc), (start + timedelta(minutes=29)).astimezone(timezone.utc),
        )
    with pytest.raises(DataContractError, match="session_date"):
        SessionSchedule(
            date(2024, 11, 28), start, start + timedelta(hours=6, minutes=30),
            start.astimezone(timezone.utc),
            (start + timedelta(hours=6, minutes=30)).astimezone(timezone.utc), False, 13,
        )


def test_bar60_requires_exactly_sixty_matching_minutes():
    start = datetime(2024, 11, 27, 9, 30, tzinfo=NY)
    end = start + timedelta(minutes=59)
    values = (Decimal("500"), Decimal("502"), Decimal("499"), Decimal("501"), Decimal("1000"))
    with pytest.raises(DataContractError, match="60 minutes"):
        Bar60mRecord(
            start, end, start.astimezone(timezone.utc), end.astimezone(timezone.utc),
            start.date(), "FUTU", "QQQ", "US.QQQ", *values, *values,
        )


def test_quality_result_requires_errors_for_a_failed_state():
    with pytest.raises(ValueError, match="requires at least one error"):
        DataQualityResult(DataStatus.DATA_QUALITY_FAILED, (), ())
```

- [ ] **Step 2: Run the focused test and verify the import failure**

Run: `python -m pytest tests/phase1_data/test_models.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'tv_quant.phase1_data'`.

- [ ] **Step 3: Implement the complete schema and error contracts**

```python
# src/tv_quant/phase1_data/errors.py
class Phase1DataError(RuntimeError):
    pass


class DataContractError(Phase1DataError):
    pass


class CalendarContractError(Phase1DataError):
    pass


class ProviderError(Phase1DataError):
    pass


class TimestampSemanticsUnverifiedError(DataContractError):
    pass


class DataQualityFailedError(Phase1DataError):
    pass


class CorporateActionsUnverifiedError(Phase1DataError):
    pass


class SourceMixingError(DataContractError):
    pass


class AggregationError(DataContractError):
    pass


class PublicationBlockedError(Phase1DataError):
    pass


class AtomicWriteError(Phase1DataError):
    pass
```

```python
# src/tv_quant/phase1_data/models.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo

from .errors import DataContractError


NEW_YORK = ZoneInfo("America/New_York")
PHASE1_SYMBOLS = frozenset({"QQQ", "SPY", "IWM", "RSP", "DIA"})


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DataContractError(f"{name} must be timezone-aware")


def _validate_interval(
    start_local: datetime,
    end_local: datetime,
    start_utc: datetime,
    end_utc: datetime,
    minutes: int,
) -> None:
    for name, value in (
        ("start_local", start_local), ("end_local", end_local),
        ("start_utc", start_utc), ("end_utc", end_utc),
    ):
        _require_aware(value, name)
    if getattr(start_local.tzinfo, "key", None) != NEW_YORK.key or getattr(end_local.tzinfo, "key", None) != NEW_YORK.key:
        raise DataContractError("local timestamps must use America/New_York")
    if start_utc.utcoffset() != timedelta(0) or end_utc.utcoffset() != timedelta(0):
        raise DataContractError("UTC timestamps must have zero offset")
    if end_utc <= start_utc or end_local <= start_local:
        raise DataContractError("bar end must follow bar start")
    if end_utc - start_utc != timedelta(minutes=minutes):
        raise DataContractError(f"bar duration must be exactly {minutes} minutes")
    if start_local.astimezone(timezone.utc) != start_utc or end_local.astimezone(timezone.utc) != end_utc:
        raise DataContractError("local and UTC timestamps must identify the same instant")


class DataStatus(StrEnum):
    VALID = "VALID"
    DATA_QUALITY_FAILED = "DATA_QUALITY_FAILED"
    DATA_ACTIONS_UNVERIFIED = "DATA_ACTIONS_UNVERIFIED"


class DataWarning(StrEnum):
    ZERO_VOLUME_WARNING = "ZERO_VOLUME_WARNING"


class TimeKeySemantics(StrEnum):
    BAR_START = "BAR_START"
    BAR_END = "BAR_END"


class TimeKeyFixtureKind(StrEnum):
    TEST = "TEST"
    PRODUCTION_CAPTURE = "PRODUCTION_CAPTURE"


class EarlyClose60mPolicy(StrEnum):
    EXCLUDE = "EXCLUDE_FROM_60M_SEQUENCE"


class CorporateActionType(StrEnum):
    SPLIT = "SPLIT"
    DIVIDEND = "DIVIDEND"


@dataclass(frozen=True)
class TimeKeyEvidence:
    fixture_version: str
    fixture_kind: TimeKeyFixtureKind
    verified: bool
    semantics: TimeKeySemantics
    source_timestamp: str
    expected_bar_start_local: datetime
    symbol: str
    provider_code: str
    ktype: str
    captured_at_utc: datetime
    futu_api_version: str
    opend_version: str
    raw_response_sha256: str
    evidence: str

    def __post_init__(self) -> None:
        _require_aware(self.expected_bar_start_local, "expected_bar_start_local")
        _require_aware(self.captured_at_utc, "captured_at_utc")
        if self.captured_at_utc.utcoffset() != timedelta(0):
            raise DataContractError("captured_at_utc must have zero offset")


@dataclass(frozen=True)
class SessionSchedule:
    session_date: date
    open_local: datetime
    close_local: datetime
    open_utc: datetime
    close_utc: datetime
    is_early_close: bool
    expected_bar_count: int

    def __post_init__(self) -> None:
        minutes = self.expected_bar_count * 30
        _validate_interval(self.open_local, self.close_local, self.open_utc, self.close_utc, minutes)
        if self.session_date != self.open_local.date():
            raise DataContractError("session_date must equal the New York open date")


@dataclass(frozen=True)
class NormalizedTimestamp:
    source_timestamp: str
    bar_start_local: datetime
    bar_end_local: datetime
    bar_start_utc: datetime
    bar_end_utc: datetime

    def __post_init__(self) -> None:
        _validate_interval(
            self.bar_start_local, self.bar_end_local,
            self.bar_start_utc, self.bar_end_utc, 30,
        )


@dataclass(frozen=True)
class Bar30mRecord:
    source_timestamp: str
    bar_start_local: datetime
    bar_end_local: datetime
    bar_start_utc: datetime
    bar_end_utc: datetime
    session_date: date
    is_regular_session: bool
    is_early_close: bool
    source: str
    symbol: str
    provider_code: str
    raw_open: Decimal
    raw_high: Decimal
    raw_low: Decimal
    raw_close: Decimal
    raw_volume: Decimal
    research_open: Decimal
    research_high: Decimal
    research_low: Decimal
    research_close: Decimal
    research_volume: Decimal
    split_factor_t: Decimal

    def __post_init__(self) -> None:
        _validate_interval(
            self.bar_start_local, self.bar_end_local,
            self.bar_start_utc, self.bar_end_utc, 30,
        )
        if self.session_date != self.bar_start_local.date():
            raise DataContractError("session_date must equal local bar start date")
        if self.symbol not in PHASE1_SYMBOLS:
            raise DataContractError(f"unsupported Phase 1 symbol: {self.symbol}")


@dataclass(frozen=True)
class Bar60mRecord:
    bar_start_local: datetime
    bar_end_local: datetime
    bar_start_utc: datetime
    bar_end_utc: datetime
    session_date: date
    source: str
    symbol: str
    provider_code: str
    raw_open: Decimal
    raw_high: Decimal
    raw_low: Decimal
    raw_close: Decimal
    raw_volume: Decimal
    research_open: Decimal
    research_high: Decimal
    research_low: Decimal
    research_close: Decimal
    research_volume: Decimal

    def __post_init__(self) -> None:
        _validate_interval(
            self.bar_start_local, self.bar_end_local,
            self.bar_start_utc, self.bar_end_utc, 60,
        )
        if self.session_date != self.bar_start_local.date():
            raise DataContractError("session_date must equal local bar start date")


@dataclass(frozen=True)
class DailyBarRecord:
    session_date: date
    source: str
    symbol: str
    provider_code: str
    raw_open: Decimal
    raw_high: Decimal
    raw_low: Decimal
    raw_close: Decimal
    raw_volume: Decimal
    research_open: Decimal
    research_high: Decimal
    research_low: Decimal
    research_close: Decimal
    research_volume: Decimal


@dataclass(frozen=True)
class CorporateAction:
    source: str
    symbol: str
    action_type: CorporateActionType
    effective_date: date
    ratio_new_over_old: Decimal
    fetched_at_utc: datetime
    source_sha256: str
    verified: bool


@dataclass(frozen=True)
class CorporateActionBatch:
    actions: tuple[CorporateAction, ...]
    source_sha256: str
    fetched_at_utc: datetime
    verified: bool


@dataclass(frozen=True)
class DataQualityResult:
    status: DataStatus
    errors: tuple[str, ...]
    warnings: tuple[DataWarning, ...]

    def __post_init__(self) -> None:
        if self.status is DataStatus.DATA_QUALITY_FAILED and not self.errors:
            raise ValueError("DATA_QUALITY_FAILED requires at least one error")

    @property
    def is_valid(self) -> bool:
        return self.status is DataStatus.VALID


@dataclass(frozen=True)
class SessionValidationResult:
    session_date: date
    status: DataStatus
    expected_bar_count: int
    actual_bar_count: int
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ManifestRequest:
    source: str
    source_version: str
    generated_at_utc: datetime
    timezone: str
    start_date: date
    end_date: date
    row_counts: Mapping[str, int]
    fields: Mapping[str, tuple[str, ...]]
    file_hashes: Mapping[str, str]
    dataset_sha256: str
    quality_status: DataStatus
    warnings: tuple[DataWarning, ...]
    calendar_library: str
    calendar_library_version: str
    calendar_schedule_hash: str
    early_close_60m_policy: EarlyClose60mPolicy
    corporate_action_content_sha256: str
    corporate_action_source_sha256: str
    corporate_actions_fetched_at_utc: datetime
    corporate_action_status: DataStatus
    time_key_fixture_kind: TimeKeyFixtureKind
    time_key_semantics: TimeKeySemantics
    time_key_fixture_sha256: str
    time_key_raw_response_sha256: str


@dataclass(frozen=True)
class DataManifest:
    schema_version: str
    dataset_id: str
    source: str
    source_version: str
    generated_at_utc: datetime
    timezone: str
    start_date: date
    end_date: date
    row_counts: Mapping[str, int]
    fields: Mapping[str, tuple[str, ...]]
    file_hashes: Mapping[str, str]
    dataset_sha256: str
    quality_status: DataStatus
    warnings: tuple[DataWarning, ...]
    calendar_library: str
    calendar_library_version: str
    calendar_schedule_hash: str
    early_close_60m_policy: EarlyClose60mPolicy
    corporate_action_content_sha256: str
    corporate_action_source_sha256: str
    corporate_actions_fetched_at_utc: datetime
    corporate_action_status: DataStatus
    time_key_fixture_kind: TimeKeyFixtureKind
    time_key_semantics: TimeKeySemantics
    time_key_fixture_sha256: str
    time_key_raw_response_sha256: str


@dataclass(frozen=True)
class DatasetPaths:
    root: Path
    staging: Path
    datasets: Path
```

At this task, `src/tv_quant/phase1_data/__init__.py` contains only a module docstring and `__version__ = "0.1.0"`; Task 10 adds the frozen public `__all__` after the entire implementation exists. It never imports the CLI.

- [ ] **Step 4: Run schema tests and the legacy regression suite**

Run: `python -m pytest tests/phase1_data/test_models.py -q`

Expected: PASS.

Run: `python -m pytest tests -q`

Expected: all existing and new tests PASS; no legacy daily behavior changes.

- [ ] **Step 5: Commit the independently reviewable schema contract**

```bash
git add src/tv_quant/phase1_data/__init__.py src/tv_quant/phase1_data/models.py src/tv_quant/phase1_data/errors.py tests/phase1_data/test_models.py
git commit -m "Add phase 1 data contracts"
```

## Task 2: Integrate XNYS schedules, DST, and schedule hashing

**Files:**
- Modify: `requirements.txt:69`
- Create: `src/tv_quant/phase1_data/calendar.py`
- Create: `tests/phase1_data/test_calendar.py`

**Interfaces:**
- Consumes: `SessionSchedule` and XNYS sessions from `exchange_calendars`.
- Produces: `TradingCalendar` protocol and `XNYSCalendar`; all schedule opens/closes are timezone-aware in local and UTC forms.

- [ ] **Step 1: Add failing calendar and DST tests**

```python
# tests/phase1_data/test_calendar.py
from datetime import date, datetime, timezone

import pytest

from tv_quant.phase1_data.calendar import XNYSCalendar
from tv_quant.phase1_data.errors import CalendarContractError


@pytest.fixture(scope="module")
def calendar():
    return XNYSCalendar()


def test_normal_weekend_holiday_and_early_close(calendar):
    normal = calendar.session(date(2024, 11, 27))
    assert normal.open_local.strftime("%H:%M") == "09:30"
    assert normal.close_local.strftime("%H:%M") == "16:00"
    assert normal.expected_bar_count == 13
    assert not normal.is_early_close
    early = calendar.session(date(2024, 11, 29))
    assert early.close_local.strftime("%H:%M") == "13:00"
    assert early.expected_bar_count == 7
    assert early.is_early_close
    for closed in (date(2024, 7, 4), date(2024, 7, 6)):
        with pytest.raises(CalendarContractError, match="not an XNYS session"):
            calendar.session(closed)


def test_dst_is_derived_from_new_york_not_a_fixed_offset(calendar):
    before_start = calendar.session(date(2024, 3, 8))
    after_start = calendar.session(date(2024, 3, 11))
    before_end = calendar.session(date(2024, 11, 1))
    after_end = calendar.session(date(2024, 11, 4))
    assert before_start.open_utc.hour == 14
    assert after_start.open_utc.hour == 13
    assert before_end.open_utc.hour == 13
    assert after_end.open_utc.hour == 14
    assert {item.open_local.hour for item in (before_start, after_start, before_end, after_end)} == {9}


def test_schedule_hash_is_stable_and_range_sensitive(calendar):
    first = calendar.schedule_hash(date(2024, 11, 25), date(2024, 11, 29))
    second = calendar.schedule_hash(date(2024, 11, 25), date(2024, 11, 29))
    changed = calendar.schedule_hash(date(2024, 11, 25), date(2024, 12, 2))
    assert len(first) == 64
    assert first == second
    assert first != changed
    assert calendar.library_name == "exchange_calendars"
    assert calendar.library_version == "4.13.2"
```

- [ ] **Step 2: Confirm failure before adding the dependency and module**

Run: `python -m pytest tests/phase1_data/test_calendar.py -q`

Expected: FAIL with `ModuleNotFoundError` for `tv_quant.phase1_data.calendar` or `exchange_calendars`.

- [ ] **Step 3: Pin the calendar dependency and implement the wrapper**

Add exactly this line to `requirements.txt`:

```text
exchange-calendars==4.13.2
```

```python
# src/tv_quant/phase1_data/calendar.py
from __future__ import annotations

import hashlib
import json
from datetime import date
from importlib.metadata import version
from typing import Protocol
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

from .errors import CalendarContractError
from .models import SessionSchedule


NEW_YORK = ZoneInfo("America/New_York")


class TradingCalendar(Protocol):
    library_name: str
    library_version: str
    def sessions(self, start: date, end: date) -> tuple[SessionSchedule, ...]: ...
    def session(self, session_date: date) -> SessionSchedule: ...
    def schedule_hash(self, start: date, end: date) -> str: ...


class XNYSCalendar:
    library_name = "exchange_calendars"

    def __init__(self) -> None:
        self._calendar = xcals.get_calendar("XNYS")
        self.library_version = version("exchange-calendars")

    def session(self, session_date: date) -> SessionSchedule:
        label = session_date.isoformat()
        if not self._calendar.is_session(label):
            raise CalendarContractError(f"{label} is not an XNYS session")
        open_utc = self._calendar.session_open(label).to_pydatetime()
        close_utc = self._calendar.session_close(label).to_pydatetime()
        open_local = open_utc.astimezone(NEW_YORK)
        close_local = close_utc.astimezone(NEW_YORK)
        minutes = int((close_utc - open_utc).total_seconds() // 60)
        if minutes <= 0 or minutes % 30:
            raise CalendarContractError(f"XNYS session {label} is not divisible into 30-minute bars")
        return SessionSchedule(
            session_date, open_local, close_local, open_utc, close_utc,
            close_local.strftime("%H:%M") != "16:00", minutes // 30,
        )

    def sessions(self, start: date, end: date) -> tuple[SessionSchedule, ...]:
        if start > end:
            raise CalendarContractError("calendar start must not follow end")
        labels = self._calendar.sessions_in_range(start.isoformat(), end.isoformat())
        return tuple(self.session(label.date()) for label in labels)

    def schedule_hash(self, start: date, end: date) -> str:
        payload = [
            {
                "session_date": item.session_date.isoformat(),
                "open_utc": item.open_utc.isoformat(),
                "close_utc": item.close_utc.isoformat(),
                "is_early_close": item.is_early_close,
                "expected_bar_count": item.expected_bar_count,
            }
            for item in self.sessions(start, end)
        ]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
```

- [ ] **Step 4: Install the exact dependency set and verify the resolved calendar version**

Run: `python -m pip install -r requirements.txt`

Expected: exit code 0; `exchange-calendars==4.13.2` is installed.

Run: `python -c "import exchange_calendars; print(exchange_calendars.__version__)"`

Expected: exactly `4.13.2`.

- [ ] **Step 5: Run calendar tests and all regressions**

Run: `python -m pytest tests/phase1_data/test_calendar.py -q`

Expected: PASS with ordinary, holiday, weekend, early-close, DST-start, DST-end, and hash cases.

Run: `python -m pytest tests -q`

Expected: PASS.

- [ ] **Step 6: Commit the calendar boundary**

```bash
git add requirements.txt src/tv_quant/phase1_data/calendar.py tests/phase1_data/test_calendar.py
git commit -m "Add XNYS phase 1 calendar"
```

## Task 3: Add provider contracts, Futu K_30M adapter, and verified time-key fixtures

**Files:**
- Create: `src/tv_quant/phase1_data/providers.py`
- Create: `src/tv_quant/phase1_data/futu.py`
- Create: `tests/phase1_data/test_futu.py`
- Create: `tests/fixtures/phase1/futu_time_key_start.json`
- Create: `tests/fixtures/phase1/futu_time_key_end.json`
- Create: `tests/fixtures/phase1/futu_time_key_unverified.json`

**Interfaces:**
- Consumes: internal bare symbols, injected Futu quote context, explicit `TEST` or `PRODUCTION_CAPTURE` time-key evidence, and unadjusted provider frames.
- Produces: `DataProvider`, `CSVProvider`, `FutuProvider`, reversible symbol mapping, `TimeKeyEvidence`, normalized timestamps, and `CorporateActionBatch` with a raw-response hash distinct from action-content identity.
- TEST evidence is permitted only for CSV/offline deterministic tests. Constructing `FutuProvider` requires verified `PRODUCTION_CAPTURE` evidence with all required metadata and a valid raw-response SHA-256; no checked-in TEST fixture can authorize a production build.

- [ ] **Step 1: Check in explicit semantic fixtures and failing tests**

File `tests/fixtures/phase1/futu_time_key_start.json`:

```json
{"fixture_version":"1","fixture_kind":"TEST","verified":true,"semantics":"BAR_START","source_timestamp":"2024-11-27 09:30:00","expected_bar_start_local":"2024-11-27T09:30:00-05:00","symbol":"QQQ","provider_code":"US.QQQ","ktype":"K_30M","captured_at_utc":"2024-11-27T15:00:00+00:00","futu_api_version":"TEST","opend_version":"TEST","raw_response_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","evidence":"synthetic start-label conversion fixture; not production evidence"}
```

File `tests/fixtures/phase1/futu_time_key_end.json`:

```json
{"fixture_version":"1","fixture_kind":"TEST","verified":true,"semantics":"BAR_END","source_timestamp":"2024-11-27 10:00:00","expected_bar_start_local":"2024-11-27T09:30:00-05:00","symbol":"QQQ","provider_code":"US.QQQ","ktype":"K_30M","captured_at_utc":"2024-11-27T15:00:00+00:00","futu_api_version":"TEST","opend_version":"TEST","raw_response_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","evidence":"synthetic end-label conversion fixture; not production evidence"}
```

File `tests/fixtures/phase1/futu_time_key_unverified.json`:

```json
{"fixture_version":"1","fixture_kind":"TEST","verified":false,"semantics":"BAR_START","source_timestamp":"2024-11-27 09:30:00","expected_bar_start_local":"2024-11-27T09:30:00-05:00","symbol":"QQQ","provider_code":"US.QQQ","ktype":"K_30M","captured_at_utc":"2024-11-27T15:00:00+00:00","futu_api_version":"TEST","opend_version":"TEST","raw_response_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","evidence":"intentionally unverified fixture"}
```

```python
# tests/phase1_data/test_futu.py
from datetime import date
from decimal import Decimal
import json
from pathlib import Path

import pandas as pd
import pytest

from tv_quant.phase1_data.errors import DataContractError, ProviderError, TimestampSemanticsUnverifiedError
from tv_quant.phase1_data.futu import (
    FutuProvider, load_time_key_fixture, normalize_futu_timestamp,
    require_futu_production_evidence, to_futu_provider_code,
)
from tv_quant.phase1_data.models import CorporateActionBatch, TimeKeyFixtureKind
from tv_quant.phase1_data.providers import CSVProvider

FIXTURES = Path("tests/fixtures/phase1")


class QuoteContext:
    def __init__(self, pages, rehab):
        self.pages = iter(pages)
        self.rehab = rehab
        self.requests = []

    def request_history_kline(self, **kwargs):
        self.requests.append(kwargs)
        return next(self.pages)

    def get_rehab(self, code):
        return 0, self.rehab


@pytest.fixture
def production_fixture(tmp_path):
    payload = json.loads((FIXTURES / "futu_time_key_start.json").read_text(encoding="utf-8"))
    payload.update({
        "fixture_kind": "PRODUCTION_CAPTURE", "verified": True,
        "futu_api_version": "10.9.0", "opend_version": "10.9.0",
        "raw_response_sha256": "d" * 64,
        "evidence": "operator compared captured raw row with XNYS session open",
    })
    path = tmp_path / "production.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_start_and_end_fixtures_normalize_to_the_same_internal_start():
    start_evidence = load_time_key_fixture(FIXTURES / "futu_time_key_start.json")
    end_evidence = load_time_key_fixture(FIXTURES / "futu_time_key_end.json")
    assert start_evidence.fixture_kind is TimeKeyFixtureKind.TEST
    start = normalize_futu_timestamp("2024-11-27 09:30:00", start_evidence.semantics)
    end = normalize_futu_timestamp("2024-11-27 10:00:00", end_evidence.semantics)
    assert start.bar_start_local == end.bar_start_local
    assert start.bar_start_utc.isoformat() == "2024-11-27T14:30:00+00:00"
    assert start.source_timestamp != end.source_timestamp


def test_test_fixture_is_allowed_offline_but_rejected_by_futu():
    evidence = load_time_key_fixture(FIXTURES / "futu_time_key_start.json")
    assert evidence.verified
    with pytest.raises(TimestampSemanticsUnverifiedError, match="PRODUCTION_CAPTURE"):
        require_futu_production_evidence(evidence, "QQQ", "US.QQQ")


def test_unverified_semantics_blocks_even_offline_use():
    with pytest.raises(TimestampSemanticsUnverifiedError, match="not verified"):
        load_time_key_fixture(FIXTURES / "futu_time_key_unverified.json")


@pytest.mark.parametrize(("field", "value"), [("raw_response_sha256", ""), ("verified", False)])
def test_production_evidence_requires_raw_hash_and_verification(production_fixture, field, value):
    payload = json.loads(production_fixture.read_text(encoding="utf-8"))
    payload[field] = value
    production_fixture.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(TimestampSemanticsUnverifiedError):
        FutuProvider(QuoteContext([], pd.DataFrame()), production_fixture, ret_ok=0, k_30m="K_30M", no_adjust="NONE", sleep=lambda _: None)


def test_symbol_mapping_is_explicit_and_csv_mismatch_is_rejected(tmp_path):
    assert to_futu_provider_code("QQQ") == "US.QQQ"
    assert to_futu_provider_code("IWM") == "US.IWM"
    csv_path = tmp_path / "mismatch.csv"
    csv_path.write_text(
        "symbol,provider_code,source_timestamp,open,high,low,close,volume\n"
        "QQQ,US.SPY,2024-11-27 09:30:00,500,502,499,501,1000\n",
        encoding="utf-8",
    )
    evidence = load_time_key_fixture(FIXTURES / "futu_time_key_start.json")
    actions = CorporateActionBatch((), "a" * 64, datetime(2024, 1, 1, tzinfo=timezone.utc), True)
    with pytest.raises(DataContractError, match="symbol/provider_code mismatch"):
        CSVProvider(csv_path, actions, evidence).fetch_30m("QQQ", date(2024, 11, 27), date(2024, 11, 27))


def test_futu_provider_pages_unadjusted_30m_rth_requests_and_preserves_source_timestamp(production_fixture):
    first = pd.DataFrame({
        "code": ["US.QQQ"], "time_key": ["2024-11-27 09:30:00"],
        "open": [500.0], "high": [502.0], "low": [499.0], "close": [501.0], "volume": [1000],
    })
    context = QuoteContext([(0, first, b"next"), (0, first.assign(time_key="2024-11-27 10:00:00"), None)], pd.DataFrame())
    provider = FutuProvider(context, production_fixture, ret_ok=0, k_30m="K_30M", no_adjust="NONE", sleep=lambda _: None)
    bars = provider.fetch_30m("QQQ", date(2024, 11, 27), date(2024, 11, 27))
    assert bars["source_timestamp"].tolist() == ["2024-11-27 09:30:00", "2024-11-27 10:00:00"]
    assert [request["page_req_key"] for request in context.requests] == [None, b"next"]
    assert all(request["ktype"] == "K_30M" and request["autype"] == "NONE" for request in context.requests)
    assert all(request["extended_time"] is False for request in context.requests)
    assert bars["symbol"].unique().tolist() == ["QQQ"]
    assert bars["provider_code"].unique().tolist() == ["US.QQQ"]


def test_vendor_split_ratio_is_inverted_to_new_shares_over_old_shares(production_fixture):
    rehab = pd.DataFrame({
        "ex_div_date": ["2022-06-06"], "split_base": [1.0], "split_ert": [2.0],
        "join_base": [0.0], "join_ert": [0.0], "split_ratio": [0.5],
    })
    context = QuoteContext([], rehab)
    provider = FutuProvider(context, production_fixture, ret_ok=0, k_30m="K_30M", no_adjust="NONE", sleep=lambda _: None)
    batch = provider.fetch_corporate_actions("QQQ", date(2020, 1, 1), date(2024, 1, 1))
    action = batch.actions[0]
    assert action.ratio_new_over_old == Decimal("2")
    assert action.verified


def test_futu_failure_is_explicit_without_provider_fallback(production_fixture):
    context = QuoteContext([(1, "permission denied", None)], pd.DataFrame())
    provider = FutuProvider(context, production_fixture, ret_ok=0, k_30m="K_30M", no_adjust="NONE", sleep=lambda _: None)
    with pytest.raises(ProviderError, match="permission denied"):
        provider.fetch_30m("QQQ", date(2024, 11, 27), date(2024, 11, 27))
```

- [ ] **Step 2: Run tests and verify the missing adapter failure**

Run: `python -m pytest tests/phase1_data/test_futu.py -q`

Expected: FAIL because `providers.py` and `futu.py` do not exist.

- [ ] **Step 3: Implement exact provider and timestamp behavior**

```python
# src/tv_quant/phase1_data/providers.py
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Protocol

import pandas as pd

from .errors import DataContractError, ProviderError
from .models import CorporateActionBatch, PHASE1_SYMBOLS, TimeKeyEvidence


class DataProvider(Protocol):
    source_name: str
    source_version: str
    def fetch_30m(self, symbol: str, start: date, end: date) -> pd.DataFrame: ...
    def fetch_corporate_actions(self, symbol: str, start: date, end: date) -> CorporateActionBatch: ...


class CSVProvider:
    source_name = "CSV"
    source_version = "fixture/1"

    def __init__(self, bars_path: Path, actions: CorporateActionBatch, time_key_evidence: TimeKeyEvidence) -> None:
        self._bars_path = Path(bars_path)
        self._actions = actions
        self.time_key_evidence = time_key_evidence

    def fetch_30m(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        frame = pd.read_csv(self._bars_path, dtype={"source_timestamp": str})
        required = {"symbol", "provider_code", "source_timestamp"}
        if missing := required.difference(frame.columns):
            raise DataContractError(f"CSV missing columns: {', '.join(sorted(missing))}")
        if symbol not in PHASE1_SYMBOLS:
            raise DataContractError(f"unsupported Phase 1 symbol: {symbol}")
        expected_code = f"US.{symbol}"
        mismatched = frame.loc[frame["symbol"].eq(symbol) & ~frame["provider_code"].eq(expected_code)]
        if not mismatched.empty:
            raise DataContractError(f"CSV symbol/provider_code mismatch for {symbol}")
        selected = frame.loc[
            frame["symbol"].str.upper().eq(symbol.upper())
            & pd.to_datetime(frame["source_timestamp"]).dt.date.between(start, end)
        ]
        if selected.empty:
            raise ProviderError(f"no CSV 30-minute rows for {symbol}")
        return selected.reset_index(drop=True)

    def fetch_corporate_actions(self, symbol: str, start: date, end: date) -> CorporateActionBatch:
        selected = tuple(action for action in self._actions.actions if action.symbol == symbol and start <= action.effective_date <= end)
        return CorporateActionBatch(
            selected, self._actions.source_sha256,
            self._actions.fetched_at_utc, self._actions.verified,
        )
```

`src/tv_quant/phase1_data/futu.py` must implement the following exact rules:

```python
NEW_YORK = ZoneInfo("America/New_York")


def load_time_key_fixture(path: str | Path) -> TimeKeyEvidence:
    raw = Path(path).read_bytes()
    payload = json.loads(raw)
    if payload.get("verified") is not True:
        raise TimestampSemanticsUnverifiedError(f"time_key fixture {path} is not verified")
    required = {
        "fixture_version", "fixture_kind", "verified", "semantics", "source_timestamp",
        "expected_bar_start_local", "symbol", "provider_code", "ktype", "captured_at_utc",
        "futu_api_version", "opend_version", "raw_response_sha256", "evidence",
    }
    if missing := required.difference(payload):
        raise TimestampSemanticsUnverifiedError(f"time_key fixture missing fields: {sorted(missing)}")
    evidence = TimeKeyEvidence(
        payload["fixture_version"], TimeKeyFixtureKind(payload["fixture_kind"]), True,
        TimeKeySemantics(payload["semantics"]), payload["source_timestamp"],
        datetime.fromisoformat(payload["expected_bar_start_local"]), payload["symbol"],
        payload["provider_code"], payload["ktype"], datetime.fromisoformat(payload["captured_at_utc"]),
        payload["futu_api_version"], payload["opend_version"],
        payload["raw_response_sha256"], payload["evidence"],
    )
    normalized = normalize_futu_timestamp(evidence.source_timestamp, evidence.semantics)
    if normalized.bar_start_local.isoformat() != payload["expected_bar_start_local"]:
        raise TimestampSemanticsUnverifiedError(f"time_key fixture {path} contradicts expected start")
    return evidence


def require_futu_production_evidence(evidence: TimeKeyEvidence, symbol: str, provider_code: str) -> None:
    if evidence.fixture_kind is not TimeKeyFixtureKind.PRODUCTION_CAPTURE:
        raise TimestampSemanticsUnverifiedError("Futu builds require PRODUCTION_CAPTURE evidence")
    if not evidence.verified or not re.fullmatch(r"[0-9a-f]{64}", evidence.raw_response_sha256):
        raise TimestampSemanticsUnverifiedError("production evidence is unverified or lacks raw SHA-256")
    if not all((evidence.futu_api_version, evidence.opend_version, evidence.evidence)):
        raise TimestampSemanticsUnverifiedError("production evidence lacks version or operator evidence")
    if (evidence.symbol, evidence.provider_code, evidence.ktype) != (symbol, provider_code, "K_30M"):
        raise TimestampSemanticsUnverifiedError("production evidence does not match requested symbol/provider/ktype")


def to_futu_provider_code(symbol: str) -> str:
    normalized = symbol.upper()
    if normalized not in PHASE1_SYMBOLS:
        raise DataContractError(f"unsupported Phase 1 symbol: {symbol}")
    return f"US.{normalized}"


def from_futu_provider_code(provider_code: str) -> str:
    if not provider_code.startswith("US."):
        raise DataContractError(f"unsupported Futu provider_code: {provider_code}")
    symbol = provider_code[3:]
    if to_futu_provider_code(symbol) != provider_code:
        raise DataContractError(f"unsupported Futu provider_code: {provider_code}")
    return symbol


def normalize_futu_timestamp(source_timestamp: str, semantics: TimeKeySemantics) -> NormalizedTimestamp:
    parsed = datetime.strptime(source_timestamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=NEW_YORK)
    bar_start_local = parsed if semantics is TimeKeySemantics.BAR_START else parsed - timedelta(minutes=30)
    bar_end_local = bar_start_local + timedelta(minutes=30)
    return NormalizedTimestamp(
        source_timestamp, bar_start_local, bar_end_local,
        bar_start_local.astimezone(timezone.utc), bar_end_local.astimezone(timezone.utc),
    )
```

```python
class FutuProvider:
    source_name = "FUTU"
    source_version = "futu-api/10.9"

    def __init__(self, quote_context, fixture_path, *, ret_ok, k_30m, no_adjust, sleep=time.sleep):
        self._context = quote_context
        self._ret_ok = ret_ok
        self._k_30m = k_30m
        self._no_adjust = no_adjust
        self._sleep = sleep
        fixture_bytes = Path(fixture_path).read_bytes()
        self.time_key_evidence = load_time_key_fixture(fixture_path)
        require_futu_production_evidence(
            self.time_key_evidence,
            self.time_key_evidence.symbol,
            self.time_key_evidence.provider_code,
        )
        self.time_key_semantics = self.time_key_evidence.semantics
        self.time_key_fixture_sha256 = hashlib.sha256(fixture_bytes).hexdigest()

    def fetch_30m(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        code = to_futu_provider_code(symbol)
        require_futu_production_evidence(self.time_key_evidence, symbol.upper(), code)
        pages = []
        page_key = None
        while True:
            self._sleep(1)
            ret, data, next_key = self._context.request_history_kline(
                code=code, start=start.isoformat(), end=end.isoformat(),
                ktype=self._k_30m, autype=self._no_adjust, max_count=1000,
                page_req_key=page_key, extended_time=False,
            )
            if ret != self._ret_ok:
                raise ProviderError(f"Futu K_30M request failed for {code}: {data}")
            if not isinstance(data, pd.DataFrame):
                raise ProviderError(f"Futu K_30M returned non-tabular data for {code}")
            pages.append(data)
            if next_key is None:
                break
            page_key = next_key
        merged = pd.concat(pages, ignore_index=True)
        required = {"code", "time_key", "open", "high", "low", "close", "volume"}
        missing = required.difference(merged.columns)
        if missing:
            raise ProviderError(f"Futu K_30M missing columns: {', '.join(sorted(missing))}")
        returned = {str(item).upper() for item in merged["code"]}
        if returned != {code}:
            raise ProviderError(f"Futu returned symbols {sorted(returned)} for {code}")
        normalized = [normalize_futu_timestamp(value, self.time_key_semantics) for value in merged["time_key"].astype(str)]
        return pd.DataFrame({
            "source_timestamp": [item.source_timestamp for item in normalized],
            "bar_start_local": [item.bar_start_local for item in normalized],
            "bar_end_local": [item.bar_end_local for item in normalized],
            "bar_start_utc": [item.bar_start_utc for item in normalized],
            "bar_end_utc": [item.bar_end_utc for item in normalized],
            "symbol": from_futu_provider_code(code), "provider_code": code,
            "open": merged["open"], "high": merged["high"], "low": merged["low"],
            "close": merged["close"], "volume": merged["volume"],
        })

    def fetch_corporate_actions(
        self, symbol: str, start: date, end: date,
    ) -> CorporateActionBatch:
        code = to_futu_provider_code(symbol)
        ret, data = self._context.get_rehab(code)
        if ret != self._ret_ok:
            raise ProviderError(f"Futu rehab request failed for {code}: {data}")
        if not isinstance(data, pd.DataFrame):
            raise ProviderError(f"Futu rehab returned non-tabular data for {code}")
        source_bytes = data.to_csv(index=False, lineterminator="\n").encode("utf-8")
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        fetched_at = datetime.now(timezone.utc)
        actions = []
        for row in data.to_dict(orient="records"):
            effective_date = date.fromisoformat(str(row["ex_div_date"]))
            if not start <= effective_date <= end:
                continue
            split_base = Decimal(str(row.get("split_base", 0)))
            split_ert = Decimal(str(row.get("split_ert", 0)))
            join_base = Decimal(str(row.get("join_base", 0)))
            join_ert = Decimal(str(row.get("join_ert", 0)))
            if split_base > 0 and split_ert > 0:
                design_ratio = split_ert / split_base
            elif join_base > 0 and join_ert > 0:
                design_ratio = join_ert / join_base
            else:
                continue
            vendor_ratio = Decimal(str(row["split_ratio"]))
            if not vendor_ratio.is_finite() or vendor_ratio <= 0:
                raise ProviderError(f"invalid Futu split_ratio on {effective_date}")
            if design_ratio != Decimal(1) / vendor_ratio:
                raise ProviderError(f"Futu split fields disagree on {effective_date}")
            actions.append(CorporateAction(
                "FUTU", symbol.upper(), CorporateActionType.SPLIT, effective_date,
                design_ratio, fetched_at, source_sha256, True,
            ))
        return CorporateActionBatch(tuple(actions), source_sha256, fetched_at, True)
```

The module imports `hashlib`, `json`, `re`, `time`, `date`, `datetime`, `timedelta`, `timezone`, `Decimal`, `Path`, `ZoneInfo`, pandas, provider/data-contract exceptions, and the model types used above. Rows without positive split or join numerator/denominator pairs remain in the raw-response hash but do not produce split adjustments. Tests also write a CSV row with `symbol=QQQ, provider_code=US.SPY` and require `CSVProvider.fetch_30m()` to raise `DataContractError`; valid CSV rows retain the bare symbol and provider code as separate columns.

- [ ] **Step 4: Run adapter tests and all regressions**

Run: `python -m pytest tests/phase1_data/test_futu.py -q`

Expected: PASS, including TEST-only offline use, TEST rejection by Futu, unverified/missing-hash production rejection, both timestamp meanings, five-symbol mapping, CSV mismatch rejection, pagination, unadjusted K_30M arguments, source preservation, supplier ratio inversion, and explicit failure.

Run: `python -m pytest tests -q`

Expected: PASS. These tests do not assert that a TEST fixture proves real Futu semantics.

- [ ] **Step 5: Perform the separate manual production-capture integration gate**

This is an operator gate, outside pytest and before the first official Futu dataset build:

1. With the approved Futu OpenD environment, capture the canonical raw response bytes for one known full-session symbol using `K_30M`, `AuType.NONE`, and `extended_time=False`.
2. Save `data/phase1/evidence/futu_time_key_<symbol>_<captured_at_utc>.json` with `fixture_kind=PRODUCTION_CAPTURE`, the real API/OpenD versions, symbol, provider code, ktype, capture time, raw-response SHA-256, source timestamp, expected New York bar start, semantics, and the operator comparison evidence.
3. Manually compare the captured row to the XNYS open/close sequence and set `verified=true` only after the label meaning is confirmed.
4. Run: `python -m tv_quant.phase1_data.cli validate-time-key --fixture <captured-json>`

Expected: `STRUCTURE_VALID MANUAL_SEMANTICS_CONFIRMATION_REQUIRED`. This command verifies schema, hashes, and time conversion only; it never claims the provider's real semantics were proved automatically. A missing raw hash, TEST kind, or `verified=false` exits nonzero and blocks the Futu build.

- [ ] **Step 6: Commit providers and TEST evidence fixtures**

```bash
git add src/tv_quant/phase1_data/providers.py src/tv_quant/phase1_data/futu.py tests/phase1_data/test_futu.py tests/fixtures/phase1/futu_time_key_start.json tests/fixtures/phase1/futu_time_key_end.json tests/fixtures/phase1/futu_time_key_unverified.json
git commit -m "Add verified Futu 30 minute adapter"
```

## Task 4: Filter RTH and validate ordinary and early-close sessions

**Files:**
- Create: `src/tv_quant/phase1_data/sessions.py`
- Create: `tests/phase1_data/helpers.py`
- Create: `tests/phase1_data/test_sessions.py`
- Create: `tests/fixtures/phase1/normal_session_2024-11-27.csv`
- Create: `tests/fixtures/phase1/early_close_2024-11-29.csv`

**Interfaces:**
- Consumes: `Bar30mRecord` sequences and one `SessionSchedule` from Task 2.
- Produces: `filter_rth_bars(...) -> tuple[Bar30mRecord, ...]` and `validate_30m_session(...) -> SessionValidationResult`.

- [ ] **Step 1: Create deterministic session fixture generation and failing tests**

The two CSV fixtures use explicit `symbol=QQQ` and `provider_code=US.QQQ` columns. `normal_session_2024-11-27.csv` has starts from `2024-11-27 09:30:00` through `15:30:00` in 30-minute increments; `early_close_2024-11-29.csv` has starts from `09:30:00` through `12:30:00`. Every row uses OHLC `500,502,499,501`, volume `1000`, and includes no premarket or postmarket row.

All Phase 1 tests import shared factories from this non-test module; no test module imports another test module:

```python
# tests/phase1_data/helpers.py
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from tv_quant.phase1_data.calendar import XNYSCalendar
from tv_quant.phase1_data.models import (
    Bar30mRecord, CorporateAction, CorporateActionBatch, CorporateActionType,
)


def make_bar30m(start_local: datetime, *, minutes: int = 30, source: str = "FUTU", symbol: str = "QQQ") -> Bar30mRecord:
    end_local = start_local + timedelta(minutes=minutes)
    one = Decimal("1")
    return Bar30mRecord(
        start_local.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
        start_local, end_local, start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc), start_local.date(), True, False,
        source, symbol, f"US.{symbol}", Decimal("500"), Decimal("502"),
        Decimal("499"), Decimal("501"), Decimal("1000"), Decimal("500"),
        Decimal("502"), Decimal("499"), Decimal("501"), Decimal("1000"), one,
    )


def scheduled_bars(session_date: date, *, symbol: str = "QQQ") -> tuple[Bar30mRecord, ...]:
    schedule = XNYSCalendar().session(session_date)
    return tuple(
        make_bar30m(schedule.open_local + index * timedelta(minutes=30), symbol=symbol)
        for index in range(schedule.expected_bar_count)
    )


def load_phase1_actions(path: Path) -> CorporateActionBatch:
    raw = path.read_bytes()
    payload = json.loads(raw)
    required = {"source", "symbol", "fetched_at_utc", "verified", "actions"}
    if missing := required.difference(payload):
        raise ValueError(f"corporate-action fixture missing fields: {sorted(missing)}")
    fetched_at = datetime.fromisoformat(payload["fetched_at_utc"])
    source_sha256 = hashlib.sha256(raw).hexdigest()
    actions = tuple(
        CorporateAction(
            payload["source"], payload["symbol"], CorporateActionType(item["action_type"]),
            date.fromisoformat(item["effective_date"]), Decimal(item["ratio_new_over_old"]),
            fetched_at, source_sha256, bool(payload["verified"]),
        )
        for item in payload["actions"]
    )
    return CorporateActionBatch(actions, source_sha256, fetched_at, bool(payload["verified"]))
```

The helper contains no pytest fixture magic, and production code never imports it.

```python
# tests/phase1_data/test_sessions.py
from dataclasses import replace
from datetime import date, timedelta

import pytest

from tv_quant.phase1_data.calendar import XNYSCalendar
from tv_quant.phase1_data.models import DataStatus
from tv_quant.phase1_data.sessions import filter_rth_bars, validate_30m_session
from tests.phase1_data.helpers import make_bar30m, scheduled_bars


def test_ordinary_session_has_exactly_thirteen_expected_bars():
    schedule = XNYSCalendar().session(date(2024, 11, 27))
    result = validate_30m_session(scheduled_bars(schedule.session_date), schedule)
    assert result.status is DataStatus.VALID
    assert (result.expected_bar_count, result.actual_bar_count) == (13, 13)


def test_early_close_has_seven_bars_with_exact_start_and_end():
    schedule = XNYSCalendar().session(date(2024, 11, 29))
    result = validate_30m_session(scheduled_bars(schedule.session_date), schedule)
    assert result.status is DataStatus.VALID
    assert (result.expected_bar_count, result.actual_bar_count) == (7, 7)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda bars: bars[:-1], "expected 13 bars"),
        (lambda bars: bars + (bars[0],), "duplicate"),
        (lambda bars: bars[:5] + (replace(bars[5], bar_start_local=bars[4].bar_start_local, bar_start_utc=bars[4].bar_start_utc),) + bars[6:], "overlap"),
        (lambda bars: (bars[1], bars[0]) + bars[2:], "strictly ordered"),
        (lambda bars: (replace(bars[0], bar_end_local=bars[0].bar_end_local + timedelta(minutes=1), bar_end_utc=bars[0].bar_end_utc + timedelta(minutes=1)),) + bars[1:], "30 minutes"),
        (lambda bars: (replace(bars[0], bar_start_local=bars[0].bar_start_local + timedelta(minutes=1), bar_start_utc=bars[0].bar_start_utc + timedelta(minutes=1)),) + bars[1:], "expected XNYS starts"),
    ],
)
def test_session_integrity_failures_are_blocking(mutate, message):
    schedule = XNYSCalendar().session(date(2024, 11, 27))
    result = validate_30m_session(mutate(scheduled_bars(schedule.session_date)), schedule)
    assert result.status is DataStatus.DATA_QUALITY_FAILED
    assert any(message in error for error in result.errors)


def test_premarket_and_postmarket_are_filtered_before_validation():
    schedule = XNYSCalendar().session(date(2024, 11, 27))
    regular = scheduled_bars(schedule.session_date)
    pre = replace(make_bar30m(schedule.open_local - timedelta(minutes=30)), is_regular_session=False)
    post = replace(make_bar30m(schedule.close_local), is_regular_session=False)
    filtered = filter_rth_bars((pre,) + regular + (post,), schedule)
    assert filtered == regular
    assert validate_30m_session(filtered, schedule).status is DataStatus.VALID


def test_early_close_wrong_count_and_wrong_bounds_fail():
    schedule = XNYSCalendar().session(date(2024, 11, 29))
    bars = scheduled_bars(schedule.session_date)
    shifted = tuple(replace(
        item,
        bar_start_local=item.bar_start_local + timedelta(minutes=30),
        bar_end_local=item.bar_end_local + timedelta(minutes=30),
        bar_start_utc=item.bar_start_utc + timedelta(minutes=30),
        bar_end_utc=item.bar_end_utc + timedelta(minutes=30),
    ) for item in bars)
    for invalid in (bars[:-1], shifted):
        assert validate_30m_session(invalid, schedule).status is DataStatus.DATA_QUALITY_FAILED
```

- [ ] **Step 2: Run tests and verify the missing session module failure**

Run: `python -m pytest tests/phase1_data/test_sessions.py -q`

Expected: FAIL importing `tv_quant.phase1_data.sessions`.

- [ ] **Step 3: Implement RTH filtering and exact schedule comparison**

```python
# src/tv_quant/phase1_data/sessions.py
from __future__ import annotations

from datetime import timedelta
from typing import Sequence

from .models import Bar30mRecord, DataStatus, SessionSchedule, SessionValidationResult


BAR_SIZE = timedelta(minutes=30)


def filter_rth_bars(bars: Sequence[Bar30mRecord], schedule: SessionSchedule) -> tuple[Bar30mRecord, ...]:
    return tuple(
        bar for bar in bars
        if bar.is_regular_session
        and bar.session_date == schedule.session_date
        and schedule.open_utc <= bar.bar_start_utc < schedule.close_utc
        and bar.bar_end_utc <= schedule.close_utc
    )


def validate_30m_session(
    bars: Sequence[Bar30mRecord], schedule: SessionSchedule,
) -> SessionValidationResult:
    items = tuple(bars)
    errors: list[str] = []
    expected_starts = tuple(schedule.open_utc + index * BAR_SIZE for index in range(schedule.expected_bar_count))
    actual_starts = tuple(item.bar_start_utc for item in items)
    if len(items) != schedule.expected_bar_count:
        errors.append(f"expected {schedule.expected_bar_count} bars, got {len(items)}")
    if len(set(actual_starts)) != len(actual_starts):
        errors.append("duplicate bar start")
    if any(left.bar_start_utc >= right.bar_start_utc for left, right in zip(items, items[1:])):
        errors.append("bars must be strictly ordered")
    if any(item.bar_end_utc - item.bar_start_utc != BAR_SIZE for item in items):
        errors.append("every bar must be exactly 30 minutes")
    if any(left.bar_end_utc > right.bar_start_utc for left, right in zip(items, items[1:])):
        errors.append("bars overlap")
    if actual_starts != expected_starts:
        errors.append("bar starts do not match expected XNYS starts")
    if any(item.session_date != schedule.session_date for item in items):
        errors.append("bar session_date differs from schedule")
    status = DataStatus.VALID if not errors else DataStatus.DATA_QUALITY_FAILED
    return SessionValidationResult(schedule.session_date, status, schedule.expected_bar_count, len(items), tuple(errors))
```

- [ ] **Step 4: Run focused and regression tests**

Run: `python -m pytest tests/phase1_data/test_sessions.py -q`

Expected: PASS for normal day, early close, missing, duplicate, overlap, ordering, length, start/end, premarket, and postmarket cases.

Run: `python -m pytest tests -q`

Expected: PASS.

- [ ] **Step 5: Commit session validation**

```bash
git add src/tv_quant/phase1_data/sessions.py tests/phase1_data/helpers.py tests/phase1_data/test_sessions.py tests/fixtures/phase1/normal_session_2024-11-27.csv tests/fixtures/phase1/early_close_2024-11-29.csv
git commit -m "Validate phase 1 RTH sessions"
```

## Task 5: Enforce OHLCV and split-factor quality

**Files:**
- Create: `src/tv_quant/phase1_data/quality.py`
- Create: `tests/phase1_data/test_quality.py`

**Interfaces:**
- Consumes: `Sequence[Bar30mRecord]`.
- Produces: `validate_ohlcv(...)` and `validate_split_factors(...)`, returning complete `DataQualityResult` objects without mutating records.

- [ ] **Step 1: Add parameterized failing quality tests**

```python
# tests/phase1_data/test_quality.py
from dataclasses import replace
from decimal import Decimal

import pytest

from tv_quant.phase1_data.models import DataStatus, DataWarning
from tv_quant.phase1_data.quality import validate_ohlcv, validate_split_factors
from tests.phase1_data.helpers import scheduled_bars


def valid_bar():
    return scheduled_bars(__import__("datetime").date(2024, 11, 27))[0]


def test_valid_ohlcv_passes_and_zero_volume_warns_without_failure():
    assert validate_ohlcv((valid_bar(),)).status is DataStatus.VALID
    zero = replace(valid_bar(), raw_volume=Decimal("0"), research_volume=Decimal("0"))
    result = validate_ohlcv((zero,))
    assert result.status is DataStatus.VALID
    assert result.warnings == (DataWarning.ZERO_VOLUME_WARNING,)


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"raw_high": Decimal("499")}, "raw high"),
        ({"raw_low": Decimal("503")}, "raw low"),
        ({"raw_high": Decimal("498"), "raw_low": Decimal("499")}, "raw high"),
        ({"research_close": Decimal("NaN")}, "finite"),
        ({"research_open": Decimal("Infinity")}, "finite"),
        ({"raw_close": Decimal("0")}, "positive"),
        ({"raw_volume": Decimal("-1")}, "volume"),
    ],
)
def test_invalid_ohlcv_is_blocking(changes, fragment):
    result = validate_ohlcv((replace(valid_bar(), **changes),))
    assert result.status is DataStatus.DATA_QUALITY_FAILED
    assert any(fragment in error for error in result.errors)


@pytest.mark.parametrize("factor", [Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity")])
def test_nonpositive_or_nonfinite_split_factor_is_blocking(factor):
    result = validate_split_factors((replace(valid_bar(), split_factor_t=factor),))
    assert result.status is DataStatus.DATA_QUALITY_FAILED
```

- [ ] **Step 2: Run tests and verify the missing validator failure**

Run: `python -m pytest tests/phase1_data/test_quality.py -q`

Expected: FAIL importing `tv_quant.phase1_data.quality`.

- [ ] **Step 3: Implement one reusable price-space validator**

```python
# src/tv_quant/phase1_data/quality.py
from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from .models import Bar30mRecord, DataQualityResult, DataStatus, DataWarning


def _finite(value: Decimal) -> bool:
    return value.is_finite()


def validate_ohlcv(bars: Sequence[Bar30mRecord]) -> DataQualityResult:
    errors: list[str] = []
    warnings: set[DataWarning] = set()
    if not bars:
        errors.append("OHLCV sequence is empty")
    for index, bar in enumerate(bars):
        for prefix in ("raw", "research"):
            open_ = getattr(bar, f"{prefix}_open")
            high = getattr(bar, f"{prefix}_high")
            low = getattr(bar, f"{prefix}_low")
            close = getattr(bar, f"{prefix}_close")
            volume = getattr(bar, f"{prefix}_volume")
            if not all(_finite(value) for value in (open_, high, low, close, volume)):
                errors.append(f"row {index} {prefix} OHLCV must be finite")
                continue
            if any(value <= 0 for value in (open_, high, low, close)):
                errors.append(f"row {index} {prefix} prices must be positive")
            if high < max(open_, close) or high < low:
                errors.append(f"row {index} {prefix} high is inconsistent")
            if low > min(open_, close):
                errors.append(f"row {index} {prefix} low is inconsistent")
            if volume < 0:
                errors.append(f"row {index} {prefix} volume must be non-negative")
            elif volume == 0:
                warnings.add(DataWarning.ZERO_VOLUME_WARNING)
    return DataQualityResult(
        DataStatus.VALID if not errors else DataStatus.DATA_QUALITY_FAILED,
        tuple(errors), tuple(sorted(warnings, key=str)),
    )


def validate_split_factors(bars: Sequence[Bar30mRecord]) -> DataQualityResult:
    errors = tuple(
        f"row {index} split_factor_t must be finite and positive"
        for index, bar in enumerate(bars)
        if not bar.split_factor_t.is_finite() or bar.split_factor_t <= 0
    )
    return DataQualityResult(
        DataStatus.VALID if not errors else DataStatus.DATA_QUALITY_FAILED,
        errors, (),
    )
```

- [ ] **Step 4: Run focused and regression tests**

Run: `python -m pytest tests/phase1_data/test_quality.py -q`

Expected: PASS for valid OHLC, invalid high/low/range, NaN, infinity, nonpositive price, negative/zero volume, and invalid split factors.

Run: `python -m pytest tests -q`

Expected: PASS.

- [ ] **Step 5: Commit quality gates**

```bash
git add src/tv_quant/phase1_data/quality.py tests/phase1_data/test_quality.py
git commit -m "Enforce phase 1 OHLCV quality"
```

## Task 6: Hash corporate actions and create raw/research split-adjusted records

**Files:**
- Create: `src/tv_quant/phase1_data/corporate_actions.py`
- Create: `tests/phase1_data/test_corporate_actions.py`
- Create: `tests/fixtures/phase1/corporate_actions.json`

**Interfaces:**
- Consumes: unmodified raw `Bar30mRecord` values and source-verified `CorporateAction` events.
- Produces: `calculate_corporate_action_content_sha256(actions) -> str` and `apply_split_adjustment(bars, actions) -> tuple[Bar30mRecord, ...]`.
- The deterministic content hash excludes `fetched_at_utc`, while `CorporateActionBatch.source_sha256` retains the raw supplier-response identity and `fetched_at_utc` remains audit metadata only.

- [ ] **Step 1: Add the canonical event fixture and failing adjustment tests**

```json
{"source":"FUTU","symbol":"QQQ","fetched_at_utc":"2024-01-01T00:00:00+00:00","verified":true,"actions":[{"action_type":"SPLIT","effective_date":"2022-06-06","ratio_new_over_old":"2"},{"action_type":"DIVIDEND","effective_date":"2023-12-20","ratio_new_over_old":"1"}]}
```

```python
# tests/phase1_data/test_corporate_actions.py
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from tv_quant.phase1_data.corporate_actions import (
    apply_split_adjustment, calculate_corporate_action_content_sha256,
)
from tv_quant.phase1_data.errors import CorporateActionsUnverifiedError
from tv_quant.phase1_data.models import CorporateAction, CorporateActionType
from tests.phase1_data.helpers import scheduled_bars


def action(kind, effective, ratio, verified=True):
    return CorporateAction("FUTU", "QQQ", kind, effective, Decimal(ratio), datetime(2024, 1, 1, tzinfo=timezone.utc), "a" * 64, verified)


def source_bar(session_date):
    return scheduled_bars(session_date)[0]


def test_no_split_keeps_raw_and_research_equal():
    adjusted = apply_split_adjustment((source_bar(date(2024, 11, 27)),), ())
    assert adjusted[0].raw_close == adjusted[0].research_close
    assert adjusted[0].split_factor_t == Decimal("1")


def test_two_for_one_adjusts_only_history_before_effective_date():
    split = action(CorporateActionType.SPLIT, date(2024, 1, 3), "2")
    before = replace(source_bar(date(2024, 1, 2)), raw_close=Decimal("100"), raw_volume=Decimal("10"))
    on_date = replace(source_bar(date(2024, 1, 3)), raw_close=Decimal("50"), raw_volume=Decimal("20"))
    adjusted = apply_split_adjustment((before, on_date), (split,))
    assert adjusted[0].research_close == Decimal("50")
    assert adjusted[0].research_volume == Decimal("20")
    assert adjusted[0].raw_close == Decimal("100")
    assert adjusted[0].raw_volume == Decimal("10")
    assert adjusted[1].split_factor_t == Decimal("1")


def test_multiple_splits_multiply_and_dividend_does_not_adjust():
    splits = (
        action(CorporateActionType.SPLIT, date(2023, 1, 1), "2"),
        action(CorporateActionType.SPLIT, date(2024, 1, 1), "3"),
        action(CorporateActionType.DIVIDEND, date(2024, 6, 1), "1"),
    )
    adjusted = apply_split_adjustment((replace(source_bar(date(2022, 1, 3)), raw_close=Decimal("600")),), splits)
    assert adjusted[0].split_factor_t == Decimal("6")
    assert adjusted[0].research_close == Decimal("100")


def test_unverified_action_blocks_adjustment():
    with pytest.raises(CorporateActionsUnverifiedError, match="unverified"):
        apply_split_adjustment((source_bar(date(2024, 1, 2)),), (action(CorporateActionType.SPLIT, date(2024, 1, 3), "2", False),))


def test_action_content_hash_is_order_and_fetch_time_invariant():
    original = (
        action(CorporateActionType.SPLIT, date(2024, 1, 3), "2"),
        action(CorporateActionType.DIVIDEND, date(2024, 1, 3), "1"),
    )
    hash_one = calculate_corporate_action_content_sha256(original)
    hash_two = calculate_corporate_action_content_sha256(tuple(reversed(original)))
    hash_three = calculate_corporate_action_content_sha256(tuple(
        replace(item, fetched_at_utc=datetime(2025, 1, 1, tzinfo=timezone.utc)) for item in original
    ))
    assert hash_one == hash_two == hash_three


@pytest.mark.parametrize(
    "mutation",
    [
        lambda item: replace(item, ratio_new_over_old=Decimal("3")),
        lambda item: replace(item, effective_date=date(2024, 1, 4)),
        lambda item: replace(item, source="CSV"),
        lambda item: replace(item, source_sha256="b" * 64),
    ],
)
def test_action_content_hash_changes_with_identity_content(mutation):
    original = action(CorporateActionType.SPLIT, date(2024, 1, 3), "2")
    assert calculate_corporate_action_content_sha256((original,)) != calculate_corporate_action_content_sha256((mutation(original),))
```

- [ ] **Step 2: Run tests and verify the missing adjustment module failure**

Run: `python -m pytest tests/phase1_data/test_corporate_actions.py -q`

Expected: FAIL importing `tv_quant.phase1_data.corporate_actions`.

- [ ] **Step 3: Implement canonical action hashing and historical split factors**

```python
# src/tv_quant/phase1_data/corporate_actions.py
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from typing import Sequence

from .errors import CorporateActionsUnverifiedError
from .models import Bar30mRecord, CorporateAction, CorporateActionType


def _canonical_actions(actions: Sequence[CorporateAction]) -> bytes:
    ordered = sorted(
        actions,
        key=lambda item: (
            item.source, item.symbol, item.action_type.value, item.effective_date,
            item.ratio_new_over_old, item.source_sha256,
        ),
    )
    rows = [
        {
            "source": action.source,
            "symbol": action.symbol,
            "action_type": action.action_type.value,
            "effective_date": action.effective_date.isoformat(),
            "ratio_new_over_old": str(action.ratio_new_over_old),
            "source_sha256": action.source_sha256,
            "verified": action.verified,
        }
        for action in ordered
    ]
    return json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")


def calculate_corporate_action_content_sha256(actions: Sequence[CorporateAction]) -> str:
    return hashlib.sha256(_canonical_actions(actions)).hexdigest()


def apply_split_adjustment(
    bars: Sequence[Bar30mRecord], actions: Sequence[CorporateAction],
) -> tuple[Bar30mRecord, ...]:
    if any(not action.verified for action in actions):
        raise CorporateActionsUnverifiedError("corporate action set contains an unverified event")
    splits = tuple(action for action in actions if action.action_type is CorporateActionType.SPLIT)
    if any(not action.ratio_new_over_old.is_finite() or action.ratio_new_over_old <= 0 for action in splits):
        raise CorporateActionsUnverifiedError("split ratio must be finite and positive")
    adjusted: list[Bar30mRecord] = []
    for bar in bars:
        factor = Decimal("1")
        for action in splits:
            if action.symbol == bar.symbol and action.effective_date > bar.session_date:
                factor *= action.ratio_new_over_old
        adjusted.append(replace(
            bar,
            research_open=bar.raw_open / factor,
            research_high=bar.raw_high / factor,
            research_low=bar.raw_low / factor,
            research_close=bar.raw_close / factor,
            research_volume=bar.raw_volume * factor,
            split_factor_t=factor,
        ))
    return tuple(adjusted)
```

- [ ] **Step 4: Run focused and regression tests**

Run: `python -m pytest tests/phase1_data/test_corporate_actions.py tests/phase1_data/test_quality.py -q`

Expected: PASS for no split, 2-for-1, cumulative factors, effective-date boundary, raw immutability, volume adjustment, unverified block, fetched-time invariance, same-date reorder invariance, ratio/date/source/source-hash sensitivity, and dividend exclusion.

Run: `python -m pytest tests -q`

Expected: PASS.

- [ ] **Step 5: Commit corporate-action adjustment**

```bash
git add src/tv_quant/phase1_data/corporate_actions.py tests/phase1_data/test_corporate_actions.py tests/fixtures/phase1/corporate_actions.json
git commit -m "Add verified split adjustment"
```

## Task 7: Aggregate same-source daily bars and strict 60-minute research bars

**Files:**
- Create: `src/tv_quant/phase1_data/aggregation.py`
- Create: `tests/phase1_data/test_aggregation.py`

**Interfaces:**
- Consumes: already filtered, session-valid, OHLCV-valid, split-adjusted `Bar30mRecord` values.
- Produces: `aggregate_daily_bars(...) -> tuple[DailyBarRecord, ...]` and `aggregate_60m_research_bars(...) -> tuple[Bar60mRecord, ...]`.

- [ ] **Step 1: Add failing aggregation and source-isolation tests**

```python
# tests/phase1_data/test_aggregation.py
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from tv_quant.phase1_data.aggregation import aggregate_60m_research_bars, aggregate_daily_bars
from tv_quant.phase1_data.calendar import XNYSCalendar
from tv_quant.phase1_data.errors import AggregationError, SourceMixingError
from tests.phase1_data.helpers import scheduled_bars


def test_two_30m_bars_aggregate_raw_and_research_independently():
    schedule = XNYSCalendar().session(date(2024, 11, 27))
    first, second = scheduled_bars(schedule.session_date)[:2]
    first = replace(first, raw_open=Decimal("10"), raw_high=Decimal("14"), raw_low=Decimal("9"), raw_close=Decimal("12"), raw_volume=Decimal("100"), research_open=Decimal("5"), research_high=Decimal("7"), research_low=Decimal("4.5"), research_close=Decimal("6"), research_volume=Decimal("200"))
    second = replace(second, raw_open=Decimal("12"), raw_high=Decimal("15"), raw_low=Decimal("11"), raw_close=Decimal("13"), raw_volume=Decimal("150"), research_open=Decimal("6"), research_high=Decimal("7.5"), research_low=Decimal("5.5"), research_close=Decimal("6.5"), research_volume=Decimal("300"))
    result = aggregate_60m_research_bars((first, second) + scheduled_bars(schedule.session_date)[2:], schedule)[0]
    assert (result.raw_open, result.raw_high, result.raw_low, result.raw_close, result.raw_volume) == (Decimal("10"), Decimal("15"), Decimal("9"), Decimal("13"), Decimal("250"))
    assert (result.research_open, result.research_high, result.research_low, result.research_close, result.research_volume) == (Decimal("5"), Decimal("7.5"), Decimal("4.5"), Decimal("6.5"), Decimal("500"))


def test_normal_session_produces_six_60m_bars_and_never_uses_1530_tail():
    schedule = XNYSCalendar().session(date(2024, 11, 27))
    bars = scheduled_bars(schedule.session_date)
    result = aggregate_60m_research_bars(bars, schedule)
    assert len(result) == 6
    assert result[-1].bar_end_local.strftime("%H:%M") == "15:30"
    assert all(item.bar_start_local.strftime("%H:%M") != "15:30" for item in result)


def test_early_close_produces_no_60m_research_bars_but_does_produce_daily():
    schedule = XNYSCalendar().session(date(2024, 11, 29))
    bars = scheduled_bars(schedule.session_date)
    assert aggregate_60m_research_bars(bars, schedule) == ()
    daily = aggregate_daily_bars(bars)
    assert len(daily) == 1
    assert daily[0].raw_open == bars[0].raw_open
    assert daily[0].raw_close == bars[-1].raw_close
    assert daily[0].raw_volume == sum(item.raw_volume for item in bars)


def test_missing_pair_cross_session_and_source_mixing_are_rejected():
    schedule = XNYSCalendar().session(date(2024, 11, 27))
    bars = scheduled_bars(schedule.session_date)
    with pytest.raises(AggregationError, match="13 validated bars"):
        aggregate_60m_research_bars(bars[:-1], schedule)
    with pytest.raises(SourceMixingError, match="single source"):
        aggregate_daily_bars(bars[:-1] + (replace(bars[-1], source="YFINANCE"),))
    other = replace(bars[1], session_date=date(2024, 11, 26))
    with pytest.raises(AggregationError, match="session_date"):
        aggregate_60m_research_bars((bars[0], other) + bars[2:], schedule)
```

- [ ] **Step 2: Run tests and verify the missing aggregation failure**

Run: `python -m pytest tests/phase1_data/test_aggregation.py -q`

Expected: FAIL importing `tv_quant.phase1_data.aggregation`.

- [ ] **Step 3: Implement strict grouping with no source fallback**

```python
# src/tv_quant/phase1_data/aggregation.py
from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from .errors import AggregationError, SourceMixingError
from .models import Bar30mRecord, Bar60mRecord, DailyBarRecord, SessionSchedule


def _one_source_and_symbol(bars: Sequence[Bar30mRecord]) -> tuple[str, str]:
    sources = {bar.source for bar in bars}
    symbols = {bar.symbol for bar in bars}
    if len(sources) != 1:
        raise SourceMixingError("aggregation requires a single source")
    if len(symbols) != 1:
        raise AggregationError("aggregation requires a single symbol")
    provider_codes = {item.provider_code for item in bars}
    if len(provider_codes) != 1:
        raise AggregationError("aggregation requires a single provider_code")
    return next(iter(sources)), next(iter(symbols)), next(iter(provider_codes))


def aggregate_daily_bars(bars: Sequence[Bar30mRecord]) -> tuple[DailyBarRecord, ...]:
    grouped: dict[object, list[Bar30mRecord]] = defaultdict(list)
    for bar in bars:
        grouped[bar.session_date].append(bar)
    result: list[DailyBarRecord] = []
    for session_date in sorted(grouped):
        items = sorted(grouped[session_date], key=lambda item: item.bar_start_utc)
        source, symbol, provider_code = _one_source_and_symbol(items)
        result.append(DailyBarRecord(
            session_date, source, symbol, provider_code,
            items[0].raw_open, max(item.raw_high for item in items), min(item.raw_low for item in items), items[-1].raw_close, sum(item.raw_volume for item in items),
            items[0].research_open, max(item.research_high for item in items), min(item.research_low for item in items), items[-1].research_close, sum(item.research_volume for item in items),
        ))
    return tuple(result)


def aggregate_60m_research_bars(
    bars: Sequence[Bar30mRecord], schedule: SessionSchedule,
) -> tuple[Bar60mRecord, ...]:
    items = tuple(bars)
    if schedule.is_early_close:
        return ()
    if len(items) != 13:
        raise AggregationError("normal session requires 13 validated bars")
    if any(item.session_date != schedule.session_date for item in items):
        raise AggregationError("cannot aggregate across session_date")
    source, symbol, provider_code = _one_source_and_symbol(items)
    result: list[Bar60mRecord] = []
    for index in range(0, 12, 2):
        first, second = items[index:index + 2]
        if first.bar_end_utc != second.bar_start_utc:
            raise AggregationError("60-minute component bar is missing")
        result.append(Bar60mRecord(
            first.bar_start_local, second.bar_end_local, first.bar_start_utc, second.bar_end_utc,
            schedule.session_date, source, symbol, provider_code,
            first.raw_open, max(first.raw_high, second.raw_high), min(first.raw_low, second.raw_low), second.raw_close, first.raw_volume + second.raw_volume,
            first.research_open, max(first.research_high, second.research_high), min(first.research_low, second.research_low), second.research_close, first.research_volume + second.research_volume,
        ))
    return tuple(result)
```

- [ ] **Step 4: Run focused and regression tests**

Run: `python -m pytest tests/phase1_data/test_aggregation.py -q`

Expected: PASS for raw/research OHLCV, six-pair construction, tail exclusion, cross-session rejection, missing component, daily ordinary/early-close aggregation, source mixing rejection, and provider-code mixing rejection.

Run: `python -m pytest tests -q`

Expected: PASS.

- [ ] **Step 5: Commit deterministic aggregation**

```bash
git add src/tv_quant/phase1_data/aggregation.py tests/phase1_data/test_aggregation.py
git commit -m "Aggregate phase 1 research bars"
```

## Task 8: Build the Data Manifest, fingerprints, and atomic immutable publisher

**Files:**
- Create: `src/tv_quant/phase1_data/manifest.py`
- Create: `src/tv_quant/phase1_data/storage.py`
- Create: `tests/phase1_data/test_manifest_storage.py`
- Modify: `.gitignore:15`

**Interfaces:**
- Consumes: canonical output bytes and a self-contained `manifest.json` that is the sole publication truth.
- Produces: file/dataset hashes, deterministic dataset identity, manifest serialization, staged-manifest validation, and immutable atomic publication.
- Publication parses the staged manifest and independently verifies schema version, blocking statuses, exact required files, every declared file hash, dataset hash, recomputed dataset ID, and destination directory name before rename.

- [ ] **Step 1: Add failing manifest, hash, and failure-injection tests**

```python
# tests/phase1_data/test_manifest_storage.py
import hashlib
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from tv_quant.phase1_data.errors import AtomicWriteError, PublicationBlockedError
from tv_quant.phase1_data.manifest import build_data_manifest, manifest_json_bytes
from tv_quant.phase1_data.models import (
    DataQualityResult, DataStatus, EarlyClose60mPolicy, ManifestRequest,
    TimeKeyFixtureKind, TimeKeySemantics,
)
from tv_quant.phase1_data.storage import (
    atomic_write_dataset, calculate_dataset_sha256, calculate_file_sha256,
)


DATA_FILES = {
    "bars_30m.csv": b"symbol,provider_code,close\nQQQ,US.QQQ,501\n",
    "bars_60m.csv": b"symbol,provider_code,close\nQQQ,US.QQQ,501\n",
    "daily.csv": b"symbol,provider_code,close\nQQQ,US.QQQ,501\n",
    "corporate_actions.json": b"[]\n",
}


def request(*, files=DATA_FILES, fetched_at=datetime(2026, 7, 18, tzinfo=timezone.utc), action_content_hash="2" * 64):
    file_hashes = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
    return ManifestRequest(
        source="FUTU", source_version="10.9", generated_at_utc=datetime(2026, 7, 18, tzinfo=timezone.utc),
        timezone="UTC", start_date=date(2024, 11, 27), end_date=date(2024, 11, 29),
        row_counts={"bars_30m.csv": 20, "bars_60m.csv": 6, "daily.csv": 2, "corporate_actions.json": 1},
        fields={"bars_30m.csv": ("bar_start_utc", "raw_open", "research_open")},
        file_hashes=file_hashes, dataset_sha256=calculate_dataset_sha256(files),
        quality_status=DataStatus.VALID, warnings=(), calendar_library="exchange_calendars",
        calendar_library_version="4.13.2", calendar_schedule_hash="3" * 64,
        early_close_60m_policy=EarlyClose60mPolicy.EXCLUDE,
        corporate_action_content_sha256=action_content_hash,
        corporate_action_source_sha256="4" * 64,
        corporate_actions_fetched_at_utc=fetched_at,
        corporate_action_status=DataStatus.VALID,
        time_key_fixture_kind=TimeKeyFixtureKind.PRODUCTION_CAPTURE,
        time_key_semantics=TimeKeySemantics.BAR_START,
        time_key_fixture_sha256="5" * 64,
        time_key_raw_response_sha256="6" * 64,
    )


def publishable(tmp_path):
    manifest = build_data_manifest(request())
    return tmp_path / "datasets" / manifest.dataset_id, {**DATA_FILES, "manifest.json": manifest_json_bytes(manifest)}


def test_manifest_contains_every_mandatory_field_and_deterministic_identity():
    manifest = build_data_manifest(request())
    assert manifest.schema_version == "phase1-data-contract/1.0.0"
    assert manifest.dataset_id.startswith("phase1-")
    assert manifest.calendar_library == "exchange_calendars"
    assert manifest.calendar_library_version == "4.13.2"
    assert manifest.calendar_schedule_hash == "3" * 64
    assert manifest.early_close_60m_policy.value == "EXCLUDE_FROM_60M_SEQUENCE"
    assert build_data_manifest(request()).dataset_id == manifest.dataset_id
    assert build_data_manifest(request(fetched_at=datetime(2027, 1, 1, tzinfo=timezone.utc))).dataset_id == manifest.dataset_id
    assert build_data_manifest(request(action_content_hash="8" * 64)).dataset_id != manifest.dataset_id


def test_file_and_dataset_hashes_are_stable_and_content_sensitive(tmp_path):
    file = tmp_path / "bars.csv"
    file.write_bytes(b"a,b\n1,2\n")
    assert calculate_file_sha256(file) == calculate_file_sha256(file)
    first = calculate_dataset_sha256({"bars.csv": file.read_bytes(), "daily.csv": b"x\n"})
    assert first == calculate_dataset_sha256({"daily.csv": b"x\n", "bars.csv": file.read_bytes()})
    assert first != calculate_dataset_sha256({"bars.csv": b"a,b\n1,3\n", "daily.csv": b"x\n"})


def test_atomic_publish_succeeds_only_after_staged_hash_validation(tmp_path):
    destination, files = publishable(tmp_path)
    result = atomic_write_dataset(destination, files)
    assert result == destination
    assert (destination / "bars_30m.csv").read_bytes() == files["bars_30m.csv"]
    assert not list((tmp_path / "staging").rglob("*"))


@pytest.mark.parametrize(("field", "value"), [
    ("quality_status", "DATA_QUALITY_FAILED"),
    ("corporate_action_status", "DATA_ACTIONS_UNVERIFIED"),
])
def test_manifest_blocking_status_never_publishes(tmp_path, field, value):
    destination, files = publishable(tmp_path)
    payload = json.loads(files["manifest.json"])
    payload[field] = value
    files["manifest.json"] = (json.dumps(payload, sort_keys=True) + "\n").encode()
    with pytest.raises(PublicationBlockedError):
        atomic_write_dataset(destination, files)
    assert not destination.exists()


@pytest.mark.parametrize("fault", ["changed_csv", "changed_manifest_hash", "wrong_directory", "missing_actions", "extra_file"])
def test_manifest_truth_faults_block_before_rename(tmp_path, fault):
    destination, files = publishable(tmp_path)
    if fault == "changed_csv":
        files["bars_30m.csv"] += b"tampered\n"
    elif fault == "changed_manifest_hash":
        payload = json.loads(files["manifest.json"])
        payload["file_hashes"]["daily.csv"] = "0" * 64
        files["manifest.json"] = (json.dumps(payload, sort_keys=True) + "\n").encode()
    elif fault == "wrong_directory":
        destination = destination.with_name("phase1-wrong")
    elif fault == "missing_actions":
        del files["corporate_actions.json"]
    else:
        files["extra.txt"] = b"not declared"
    with pytest.raises((AtomicWriteError, PublicationBlockedError)):
        atomic_write_dataset(destination, files)
    assert not destination.exists()


def test_existing_valid_dataset_is_never_overwritten(tmp_path):
    destination, files = publishable(tmp_path)
    destination.mkdir(parents=True)
    valid = destination / "bars_30m.csv"
    valid.write_bytes(b"old-valid")
    with pytest.raises(FileExistsError):
        atomic_write_dataset(destination, files)
    assert valid.read_bytes() == b"old-valid"


def test_replace_failure_cleans_staging_and_preserves_other_datasets(tmp_path, monkeypatch):
    other = tmp_path / "datasets" / "phase1-old"
    other.mkdir(parents=True)
    (other / "manifest.json").write_bytes(b"old")
    destination, files = publishable(tmp_path)
    monkeypatch.setattr("tv_quant.phase1_data.storage.os.replace", lambda *_: (_ for _ in ()).throw(OSError("disk fault")))
    with pytest.raises(AtomicWriteError, match="disk fault"):
        atomic_write_dataset(destination, files)
    assert (other / "manifest.json").read_bytes() == b"old"
    assert not list((tmp_path / "staging").rglob(destination.name))
```

- [ ] **Step 2: Run tests and verify missing manifest/storage modules**

Run: `python -m pytest tests/phase1_data/test_manifest_storage.py -q`

Expected: FAIL importing `manifest` or `storage`.

- [ ] **Step 3: Implement canonical identity and atomic publication**

```python
# src/tv_quant/phase1_data/manifest.py
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Mapping

from .models import DataManifest, ManifestRequest


SCHEMA_VERSION = "phase1-data-contract/1.0.0"


def calculate_dataset_id(manifest_payload: Mapping[str, object]) -> str:
    identity_input = {
        "schema_version": SCHEMA_VERSION,
        "dataset_sha256": manifest_payload["dataset_sha256"],
        "calendar_schedule_hash": manifest_payload["calendar_schedule_hash"],
        "corporate_action_content_sha256": manifest_payload["corporate_action_content_sha256"],
        "corporate_action_source_sha256": manifest_payload["corporate_action_source_sha256"],
        "time_key_fixture_sha256": manifest_payload["time_key_fixture_sha256"],
        "time_key_raw_response_sha256": manifest_payload["time_key_raw_response_sha256"],
        "early_close_60m_policy": str(manifest_payload["early_close_60m_policy"]),
    }
    identity = hashlib.sha256(json.dumps(identity_input, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return f"phase1-{identity[:24]}"


def build_data_manifest(request: ManifestRequest) -> DataManifest:
    payload = asdict(request)
    payload["early_close_60m_policy"] = request.early_close_60m_policy.value
    return DataManifest(SCHEMA_VERSION, calculate_dataset_id(payload), **asdict(request))


def manifest_json_bytes(manifest: DataManifest) -> bytes:
    payload = asdict(manifest)
    payload["generated_at_utc"] = manifest.generated_at_utc.isoformat()
    payload["start_date"] = manifest.start_date.isoformat()
    payload["end_date"] = manifest.end_date.isoformat()
    payload["quality_status"] = manifest.quality_status.value
    payload["warnings"] = [item.value for item in manifest.warnings]
    payload["early_close_60m_policy"] = manifest.early_close_60m_policy.value
    payload["corporate_actions_fetched_at_utc"] = manifest.corporate_actions_fetched_at_utc.isoformat()
    payload["corporate_action_status"] = manifest.corporate_action_status.value
    payload["time_key_fixture_kind"] = manifest.time_key_fixture_kind.value
    payload["time_key_semantics"] = manifest.time_key_semantics.value
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
```

```python
# src/tv_quant/phase1_data/storage.py
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Mapping

from .errors import AtomicWriteError, PublicationBlockedError
from .manifest import SCHEMA_VERSION, calculate_dataset_id


REQUIRED_DATA_FILES = frozenset({
    "bars_30m.csv", "bars_60m.csv", "daily.csv", "corporate_actions.json",
})


def calculate_file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def calculate_dataset_sha256(files: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256()
    for relative_name in sorted(files):
        content_hash = hashlib.sha256(files[relative_name]).hexdigest()
        digest.update(relative_name.encode("utf-8") + b"\0" + content_hash.encode("ascii") + b"\n")
    return digest.hexdigest()


def atomic_write_dataset(
    destination: Path,
    files: Mapping[str, bytes],
) -> Path:
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(f"immutable dataset already exists: {destination}")
    if set(files) != REQUIRED_DATA_FILES | {"manifest.json"}:
        raise PublicationBlockedError("publication requires exactly the declared Phase 1 files")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # destination=data/phase1/datasets/<dataset_id>; stage at the frozen runtime path.
    phase1_root = destination.parent.parent
    run_root = phase1_root / "staging" / uuid.uuid4().hex
    staging = run_root / destination.name
    staging.mkdir(parents=True)
    try:
        for relative_name, content in files.items():
            target = staging / relative_name
            with target.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())

        try:
            manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AtomicWriteError(f"invalid staged manifest: {error}") from error
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise PublicationBlockedError("unsupported manifest schema_version")
        if manifest.get("quality_status") != "VALID":
            raise PublicationBlockedError("DATA_QUALITY_FAILED prevents publication")
        if manifest.get("corporate_action_status") != "VALID":
            raise PublicationBlockedError("DATA_ACTIONS_UNVERIFIED prevents publication")
        declared = manifest.get("file_hashes")
        if not isinstance(declared, dict) or set(declared) != REQUIRED_DATA_FILES:
            raise AtomicWriteError("manifest file_hashes must declare the exact data files")
        actual_hashes = {name: calculate_file_sha256(staging / name) for name in REQUIRED_DATA_FILES}
        if actual_hashes != declared:
            raise AtomicWriteError("staged file hashes contradict manifest")
        staged_bytes = {name: (staging / name).read_bytes() for name in REQUIRED_DATA_FILES}
        if calculate_dataset_sha256(staged_bytes) != manifest.get("dataset_sha256"):
            raise AtomicWriteError("staged dataset hash contradicts manifest")
        recomputed_id = calculate_dataset_id(manifest)
        if manifest.get("dataset_id") != recomputed_id or destination.name != recomputed_id:
            raise AtomicWriteError("dataset identity or destination directory is inconsistent")
        os.replace(staging, destination)
    except Exception as error:
        shutil.rmtree(run_root, ignore_errors=True)
        if isinstance(error, (AtomicWriteError, FileExistsError, PublicationBlockedError)):
            raise
        raise AtomicWriteError(str(error)) from error
    shutil.rmtree(run_root, ignore_errors=True)
    return destination
```

Add these lines to `.gitignore`:

```text
data/phase1/staging/
data/phase1/datasets/
```

- [ ] **Step 4: Run focused tests and full regression**

Run: `python -m pytest tests/phase1_data/test_manifest_storage.py -q`

Expected: PASS for mandatory fields, fetch-time-invariant identity, repeated raw-response identity, content-sensitive SHA-256, successful atomic replacement, manifest status gates, changed CSV, changed declared hash, wrong destination name, missing corporate actions, extra file, immutable destination, and injected rename failure with cleanup.

Run: `python -m pytest tests -q`

Expected: PASS.

- [ ] **Step 5: Commit manifest and publication boundaries**

```bash
git add .gitignore src/tv_quant/phase1_data/manifest.py src/tv_quant/phase1_data/storage.py tests/phase1_data/test_manifest_storage.py
git commit -m "Publish immutable phase 1 datasets"
```

## Task 9: Orchestrate the pipeline and isolate the new CLI from the legacy EMA system

**Files:**
- Create: `src/tv_quant/phase1_data/pipeline.py`
- Create: `src/tv_quant/phase1_data/cli.py`
- Create: `tests/phase1_data/test_pipeline_cli.py`

**Interfaces:**
- Consumes: explicit provider, calendar, time-key evidence, output root, symbol, and date range.
- Produces: `BuildDatasetRequest`, `PipelineResult`, `build_phase1_dataset`, and CLI exit codes `0`, `2`, `3`, `4`, `5`, `6`.

- [ ] **Step 1: Add failing orchestration, gate, and CLI-isolation tests**

```python
# tests/phase1_data/test_pipeline_cli.py
from datetime import date
from pathlib import Path

import pytest

from tv_quant.cli import build_parser as legacy_parser
from tv_quant.phase1_data.cli import EXIT_ACTIONS, EXIT_PROVIDER, EXIT_PUBLICATION, EXIT_QUALITY, main
from tv_quant.phase1_data.errors import (
    AggregationError, AtomicWriteError, CalendarContractError,
    CorporateActionsUnverifiedError, DataContractError, DataQualityFailedError,
    ProviderError, PublicationBlockedError, SourceMixingError,
)
from tv_quant.phase1_data.pipeline import BuildDatasetRequest, PipelineResult


def test_legacy_cli_keeps_only_daily_download_and_backtest_commands():
    assert legacy_parser().parse_args(["download"]).command == "download"
    assert legacy_parser().parse_args(["backtest", "--input", "x", "--out-dir", "y"]).command == "backtest"
    with pytest.raises(SystemExit):
        legacy_parser().parse_args(["build"])


def test_new_request_rejects_legacy_input_paths_and_non_phase1_output():
    with pytest.raises(ValueError, match="data/phase1"):
        BuildDatasetRequest("QQQ", date(2024, 1, 1), date(2024, 1, 2), Path("data/raw"), Path("fixture.json"))


@pytest.mark.parametrize("symbol", ["QQQ", "SPY", "IWM", "RSP", "DIA"])
def test_all_frozen_phase1_symbols_are_accepted(symbol):
    assert BuildDatasetRequest(symbol, date(2024, 1, 1), date(2024, 1, 2), Path("data/phase1"), Path("fixture.json")).symbol == symbol


@pytest.mark.parametrize(
    ("error", "exit_code"),
    [
        (ProviderError("Futu failed"), EXIT_PROVIDER),
        (DataQualityFailedError("bad bars"), EXIT_QUALITY),
        (CalendarContractError("bad session"), EXIT_QUALITY),
        (DataContractError("bad record"), EXIT_QUALITY),
        (SourceMixingError("mixed source"), EXIT_QUALITY),
        (AggregationError("bad aggregate"), EXIT_QUALITY),
        (CorporateActionsUnverifiedError("bad actions"), EXIT_ACTIONS),
        (PublicationBlockedError("blocked"), EXIT_PUBLICATION),
        (AtomicWriteError("rename failed"), EXIT_PUBLICATION),
        (FileExistsError("immutable destination"), EXIT_PUBLICATION),
    ],
)
def test_cli_maps_blocking_failures_to_fixed_nonzero_codes(monkeypatch, capsys, error, exit_code):
    monkeypatch.setattr("tv_quant.phase1_data.cli._execute_build", lambda _args: (_ for _ in ()).throw(error))
    code = main(["build", "--symbol", "QQQ", "--start", "2024-11-27", "--end", "2024-11-29", "--provider", "csv", "--bars", "bars.csv", "--actions", "actions.json", "--time-key-fixture", "fixture.json", "--output-root", "data/phase1"])
    assert code == exit_code
    assert str(error) in capsys.readouterr().err


def test_cli_success_prints_immutable_dataset_path(monkeypatch, capsys, tmp_path):
    destination = tmp_path / "data" / "phase1" / "datasets" / "phase1-abc"
    monkeypatch.setattr("tv_quant.phase1_data.cli._execute_build", lambda _args: PipelineResult("phase1-abc", destination))
    code = main(["build", "--symbol", "QQQ", "--start", "2024-11-27", "--end", "2024-11-29", "--provider", "csv", "--bars", "bars.csv", "--actions", "actions.json", "--time-key-fixture", "fixture.json", "--output-root", str(tmp_path / "data" / "phase1")])
    assert code == 0
    assert str(destination) in capsys.readouterr().out
```

- [ ] **Step 2: Run tests and verify the missing pipeline/CLI failure**

Run: `python -m pytest tests/phase1_data/test_pipeline_cli.py -q`

Expected: FAIL importing the isolated pipeline or CLI.

- [ ] **Step 3: Implement deterministic orchestration and fixed exit codes**

```python
# src/tv_quant/phase1_data/pipeline.py
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

from .aggregation import aggregate_60m_research_bars, aggregate_daily_bars
from .calendar import TradingCalendar
from .corporate_actions import (
    apply_split_adjustment, calculate_corporate_action_content_sha256,
)
from .errors import CorporateActionsUnverifiedError, DataQualityFailedError
from .futu import normalize_futu_timestamp
from .manifest import build_data_manifest, manifest_json_bytes
from .models import (
    PHASE1_SYMBOLS, Bar30mRecord, Bar60mRecord, CorporateAction, DailyBarRecord,
    DataQualityResult, DataStatus, EarlyClose60mPolicy, ManifestRequest,
    TimeKeyEvidence, TimeKeySemantics,
)
from .quality import validate_ohlcv, validate_split_factors
from .providers import DataProvider
from .sessions import filter_rth_bars, validate_30m_session
from .storage import atomic_write_dataset, calculate_dataset_sha256


@dataclass(frozen=True)
class BuildDatasetRequest:
    symbol: str
    start: date
    end: date
    output_root: Path
    time_key_fixture: Path

    def __post_init__(self) -> None:
        normalized = self.output_root.as_posix().rstrip("/")
        if not normalized.endswith("data/phase1"):
            raise ValueError("output_root must end with data/phase1")
        if self.symbol not in PHASE1_SYMBOLS:
            raise ValueError(f"unsupported Phase 1 symbol: {self.symbol}")
        if self.start > self.end:
            raise ValueError("start must not follow end")


@dataclass(frozen=True)
class PipelineResult:
    dataset_id: str
    destination: Path


def _csv_bytes(records, record_type) -> bytes:
    columns = [field.name for field in fields(record_type)]
    frame = pd.DataFrame(asdict(record) for record in records)
    frame = frame.reindex(columns=columns)
    for column in frame.columns:
        if column.endswith("_local") or column.endswith("_utc") or column == "session_date":
            frame[column] = frame[column].astype(str)
    return frame.to_csv(index=False, lineterminator="\n").encode("utf-8")


def _actions_bytes(actions: tuple[CorporateAction, ...]) -> bytes:
    ordered = sorted(actions, key=lambda item: (
        item.source, item.symbol, item.action_type.value, item.effective_date,
        item.ratio_new_over_old, item.source_sha256,
    ))
    payload = [{
        "source": action.source, "symbol": action.symbol,
        "action_type": action.action_type.value,
        "effective_date": action.effective_date.isoformat(),
        "ratio_new_over_old": str(action.ratio_new_over_old),
        "source_sha256": action.source_sha256, "verified": action.verified,
    } for action in ordered]
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _records_from_frame(
    frame: pd.DataFrame, source: str, symbol: str, schedules,
    semantics: TimeKeySemantics,
) -> tuple[Bar30mRecord, ...]:
    schedule_by_date = {item.session_date: item for item in schedules}
    records = []
    for row in frame.to_dict(orient="records"):
        normalized = normalize_futu_timestamp(str(row["source_timestamp"]), semantics)
        session_date = normalized.bar_start_local.date()
        schedule = schedule_by_date.get(session_date)
        if schedule is None:
            raise DataQualityFailedError(f"source row falls on non-XNYS date {session_date}")
        regular = schedule.open_utc <= normalized.bar_start_utc < schedule.close_utc
        raw_open = Decimal(str(row["open"]))
        raw_high = Decimal(str(row["high"]))
        raw_low = Decimal(str(row["low"]))
        raw_close = Decimal(str(row["close"]))
        raw_volume = Decimal(str(row["volume"]))
        records.append(Bar30mRecord(
            normalized.source_timestamp, normalized.bar_start_local, normalized.bar_end_local,
            normalized.bar_start_utc, normalized.bar_end_utc, session_date, regular,
            schedule.is_early_close, source, symbol, str(row["provider_code"]), raw_open, raw_high, raw_low,
            raw_close, raw_volume, raw_open, raw_high, raw_low, raw_close, raw_volume,
            Decimal("1"),
        ))
    return tuple(records)


def build_phase1_dataset(
    request: BuildDatasetRequest,
    provider: DataProvider,
    calendar: TradingCalendar,
) -> PipelineResult:
    evidence = provider.time_key_evidence
    fixture_hash = hashlib.sha256(request.time_key_fixture.read_bytes()).hexdigest()
    schedules = calendar.sessions(request.start, request.end)
    frame = provider.fetch_30m(request.symbol, request.start, request.end)
    action_batch = provider.fetch_corporate_actions(request.symbol, request.start, request.end)
    actions = action_batch.actions
    if not action_batch.verified or any(not action.verified for action in actions):
        raise CorporateActionsUnverifiedError("corporate action set contains an unverified event")
    records = _records_from_frame(frame, provider.source_name, request.symbol, schedules, evidence.semantics)
    valid_sessions = []
    session_errors = []
    for schedule in schedules:
        filtered = filter_rth_bars(records, schedule)
        validation = validate_30m_session(filtered, schedule)
        if validation.status is not DataStatus.VALID:
            session_errors.extend(f"{schedule.session_date}: {error}" for error in validation.errors)
        else:
            valid_sessions.extend(filtered)
    if session_errors:
        raise DataQualityFailedError("; ".join(session_errors))

    adjusted = apply_split_adjustment(tuple(valid_sessions), actions)
    ohlcv = validate_ohlcv(adjusted)
    factors = validate_split_factors(adjusted)
    quality_errors = ohlcv.errors + factors.errors
    quality = DataQualityResult(
        DataStatus.VALID if not quality_errors else DataStatus.DATA_QUALITY_FAILED,
        quality_errors, ohlcv.warnings,
    )
    if not quality.is_valid:
        raise DataQualityFailedError("; ".join(quality.errors))

    daily = aggregate_daily_bars(adjusted)
    bars_60m = tuple(
        item
        for schedule in schedules
        for item in aggregate_60m_research_bars(
            tuple(bar for bar in adjusted if bar.session_date == schedule.session_date), schedule,
        )
    )
    files = {
        "bars_30m.csv": _csv_bytes(adjusted, Bar30mRecord),
        "bars_60m.csv": _csv_bytes(bars_60m, Bar60mRecord),
        "daily.csv": _csv_bytes(daily, DailyBarRecord),
        "corporate_actions.json": _actions_bytes(actions),
    }
    file_hashes = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
    dataset_hash = calculate_dataset_sha256(files)
    manifest = build_data_manifest(ManifestRequest(
        source=provider.source_name, source_version=provider.source_version,
        generated_at_utc=datetime.now(timezone.utc), timezone="UTC",
        start_date=request.start, end_date=request.end,
        row_counts={
            "bars_30m.csv": len(adjusted), "bars_60m.csv": len(bars_60m),
            "daily.csv": len(daily), "corporate_actions.json": len(actions),
        },
        fields={
            "bars_30m.csv": tuple(field.name for field in fields(Bar30mRecord)),
            "bars_60m.csv": tuple(field.name for field in fields(Bar60mRecord)),
            "daily.csv": tuple(field.name for field in fields(DailyBarRecord)),
        },
        file_hashes=file_hashes, dataset_sha256=dataset_hash,
        quality_status=quality.status, warnings=quality.warnings,
        calendar_library=calendar.library_name, calendar_library_version=calendar.library_version,
        calendar_schedule_hash=calendar.schedule_hash(request.start, request.end),
        early_close_60m_policy=EarlyClose60mPolicy.EXCLUDE,
        corporate_action_content_sha256=calculate_corporate_action_content_sha256(actions),
        corporate_action_source_sha256=action_batch.source_sha256,
        corporate_actions_fetched_at_utc=action_batch.fetched_at_utc,
        corporate_action_status=DataStatus.VALID,
        time_key_fixture_kind=evidence.fixture_kind,
        time_key_semantics=evidence.semantics,
        time_key_fixture_sha256=fixture_hash,
        time_key_raw_response_sha256=evidence.raw_response_sha256,
    ))
    files["manifest.json"] = manifest_json_bytes(manifest)
    destination = request.output_root / "datasets" / manifest.dataset_id
    atomic_write_dataset(destination, files)
    return PipelineResult(manifest.dataset_id, destination)
```

```python
# src/tv_quant/phase1_data/cli.py
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from .calendar import XNYSCalendar
from .errors import (
    AggregationError, AtomicWriteError, CalendarContractError,
    CorporateActionsUnverifiedError, DataContractError, DataQualityFailedError,
    ProviderError, PublicationBlockedError, SourceMixingError,
    TimestampSemanticsUnverifiedError,
)
from .futu import FutuProvider, load_time_key_fixture
from .models import PHASE1_SYMBOLS, CorporateAction, CorporateActionBatch, CorporateActionType
from .pipeline import BuildDatasetRequest, PipelineResult, build_phase1_dataset
from .providers import CSVProvider

EXIT_OK = 0
EXIT_ARGUMENT = 2
EXIT_PROVIDER = 3
EXIT_QUALITY = 4
EXIT_ACTIONS = 5
EXIT_PUBLICATION = 6


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tv_quant.phase1_data")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-time-key")
    validate.add_argument("--fixture", type=Path, required=True)
    build = commands.add_parser("build")
    build.add_argument("--symbol", choices=tuple(sorted(PHASE1_SYMBOLS)), required=True)
    build.add_argument("--start", type=date.fromisoformat, required=True)
    build.add_argument("--end", type=date.fromisoformat, required=True)
    build.add_argument("--provider", choices=("futu", "csv"), required=True)
    build.add_argument("--bars", type=Path)
    build.add_argument("--actions", type=Path)
    build.add_argument("--time-key-fixture", type=Path, required=True)
    build.add_argument("--output-root", type=Path, default=Path("data/phase1"))
    return parser


def _load_actions(path: Path) -> CorporateActionBatch:
    raw = path.read_bytes()
    payload = json.loads(raw)
    fetched_at = datetime.fromisoformat(payload["fetched_at_utc"])
    source_hash = hashlib.sha256(raw).hexdigest()
    actions = tuple(
        CorporateAction(
            payload["source"], payload["symbol"], CorporateActionType(row["action_type"]),
            date.fromisoformat(row["effective_date"]), Decimal(row["ratio_new_over_old"]),
            fetched_at, source_hash, bool(payload["verified"]),
        )
        for row in payload["actions"]
    )
    return CorporateActionBatch(actions, source_hash, fetched_at, bool(payload["verified"]))


def _execute_build(args: argparse.Namespace) -> PipelineResult:
    evidence = load_time_key_fixture(args.time_key_fixture)
    request = BuildDatasetRequest(
        args.symbol, args.start, args.end, args.output_root, args.time_key_fixture,
    )
    calendar = XNYSCalendar()
    if args.provider == "csv":
        if args.bars is None or args.actions is None:
            raise ValueError("csv provider requires --bars and --actions")
        provider = CSVProvider(args.bars, _load_actions(args.actions), evidence)
        return build_phase1_dataset(request, provider, calendar)

    from futu import AuType, KLType, OpenQuoteContext, RET_OK

    context = OpenQuoteContext(host="127.0.0.1", port=11111)
    try:
        provider = FutuProvider(
            context, args.time_key_fixture, ret_ok=RET_OK,
            k_30m=KLType.K_30M, no_adjust=AuType.NONE,
        )
        return build_phase1_dataset(request, provider, calendar)
    finally:
        context.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate-time-key":
            evidence = load_time_key_fixture(args.fixture)
            digest = hashlib.sha256(args.fixture.read_bytes()).hexdigest()
            print(f"STRUCTURE_VALID MANUAL_SEMANTICS_CONFIRMATION_REQUIRED {evidence.semantics.value} {digest}")
            return EXIT_OK
        result = _execute_build(args)
        print(result.destination)
        return EXIT_OK
    except (ProviderError, TimestampSemanticsUnverifiedError) as error:
        print(error, file=sys.stderr)
        return EXIT_PROVIDER
    except (
        DataQualityFailedError, CalendarContractError, DataContractError,
        SourceMixingError, AggregationError,
    ) as error:
        print(error, file=sys.stderr)
        return EXIT_QUALITY
    except CorporateActionsUnverifiedError as error:
        print(error, file=sys.stderr)
        return EXIT_ACTIONS
    except (PublicationBlockedError, AtomicWriteError, FileExistsError) as error:
        print(error, file=sys.stderr)
        return EXIT_PUBLICATION
    except ValueError as error:
        print(error, file=sys.stderr)
        return EXIT_ARGUMENT


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run CLI isolation, focused pipeline, and regression tests**

Run: `python -m pytest tests/phase1_data/test_pipeline_cli.py -q`

Expected: PASS; legacy parser rejects `build`, Phase 1 paths reject `data/raw`, all five symbols are accepted, every frozen domain exception maps to exit 3/4/5/6 (including all publication exceptions), no domain failure escapes as exit 1, and successful output is an immutable dataset path.

Run: `python -m tv_quant.phase1_data.cli --help`

Expected: exit 0 and help containing `validate-time-key` and `build`.

Run: `python -m pytest tests -q`

Expected: PASS.

- [ ] **Step 5: Commit the isolated pipeline and CLI**

```bash
git add src/tv_quant/phase1_data/pipeline.py src/tv_quant/phase1_data/cli.py tests/phase1_data/test_pipeline_cli.py
git commit -m "Add isolated phase 1 data pipeline"
```

## Task 10: Add offline acceptance coverage, operator documentation, and final verification

**Files:**
- Create: `tests/phase1_data/test_public_contract.py`
- Create: `tests/phase1_data/test_phase1_acceptance.py`
- Create: `docs/phase1-data-contract.md`
- Modify: `src/tv_quant/phase1_data/__init__.py`

**Interfaces:**
- Consumes: checked-in CSV/action/time fixtures and all Phase 1 public interfaces.
- Produces: one network-free end-to-end proof, a documented operator contract, and final public exports. It does not download data or run a strategy.

- [ ] **Step 1: Add the public-contract red test first**

```python
# tests/phase1_data/test_public_contract.py
from pathlib import Path

import tv_quant.phase1_data as phase1_data


def test_frozen_public_exports_and_operator_document_exist():
    required = {
        "PHASE1_SYMBOLS", "BuildDatasetRequest", "PipelineResult",
        "build_phase1_dataset", "DataProvider", "CSVProvider", "FutuProvider",
        "load_time_key_fixture", "calculate_dataset_id", "atomic_write_dataset",
    }
    assert required <= set(phase1_data.__all__)
    document = Path("docs/phase1-data-contract.md")
    assert document.is_file()
    text = document.read_text(encoding="utf-8")
    for heading in ("Scope and exclusions", "Data sources", "Time contract", "Commands", "Exit codes"):
        assert f"## {heading}" in text
```

- [ ] **Step 2: Run the public-contract test and confirm the intentional red reason**

Run: `python -m pytest tests/phase1_data/test_public_contract.py -q`

Expected: FAIL only because Task 1 intentionally deferred `__all__` and `docs/phase1-data-contract.md` does not yet exist. It must not fail because the pipeline is incomplete.

- [ ] **Step 3: Complete public exports and operator documentation**

`src/tv_quant/phase1_data/__init__.py` must export every name under **Frozen Public Interfaces** and set `__all__` to that exact list. It must not export Futu SDK objects or import `cli.py`.

Create `docs/phase1-data-contract.md` with these exact operational sections:

1. `Scope and exclusions`: list Phase 1 contents and every Phase 2+ exclusion from Global Constraints; state that QQQ, SPY, IWM, RSP, and DIA are the complete Phase 1 allow-list.
2. `Data sources`: Futu unadjusted K_30M primary input, no silent fallback, Futu 30-minute history availability risk, and CSV only as an explicit test/import provider.
3. `Time contract`: XNYS, America/New_York localization, UTC storage, TEST versus PRODUCTION_CAPTURE, manual semantics gate, ordinary/early-close counts, and DST examples. State that `validate-time-key` checks structure/hash/conversion but does not prove real vendor semantics.
4. `Price contract`: immutable raw fields, split-only research fields, supplier ratio inversion, dividend exclusion, content hash, raw-response hash, and fetched-time audit metadata.
5. `Runtime layout`: the exact staging/datasets/evidence tree and immutable dataset-id usage.
6. `Commands`: `validate-time-key`, CSV build, and Futu build examples; explicitly list all five allowed `--symbol` values and include no credentials.
7. `Exit codes`: 0 success, 2 arguments, 3 provider/time fixture, 4 quality/calendar/data contract/source/aggregation, 5 actions, 6 publication/atomic write/existing destination.
8. `Legacy isolation`: existing daily download/backtest commands and `data/raw` remain separate and cannot be inputs to Phase 1.
9. `Manifest fields`: enumerate every `DataManifest` field and distinguish file, dataset, calendar, action-content, action-source, time-fixture, and raw-response hashes.
10. `Residual risks`: Futu time semantics evidence, supplier history limits/revisions, corporate-action revisions, calendar-version changes, and 30-minute bars not proving tick-level paths.

- [ ] **Step 4: Run the public-contract test green before adding acceptance coverage**

Run: `python -m pytest tests/phase1_data/test_public_contract.py -q`

Expected: PASS.

- [ ] **Step 5: Add the offline end-to-end acceptance tests**

```python
# tests/phase1_data/test_phase1_acceptance.py
import json
from datetime import date
from pathlib import Path

import pytest

from tv_quant.phase1_data.calendar import XNYSCalendar
from tv_quant.phase1_data.errors import DataQualityFailedError
from tv_quant.phase1_data.futu import load_time_key_fixture
from tv_quant.phase1_data.pipeline import BuildDatasetRequest, build_phase1_dataset
from tv_quant.phase1_data.providers import CSVProvider
from tests.phase1_data.helpers import load_phase1_actions

FIXTURES = Path("tests/fixtures/phase1")


def test_normal_and_early_close_publish_expected_files_and_manifest(tmp_path):
    combined = tmp_path / "bars.csv"
    combined.write_text(
        (FIXTURES / "normal_session_2024-11-27.csv").read_text(encoding="utf-8").rstrip()
        + "\n"
        + "\n".join((FIXTURES / "early_close_2024-11-29.csv").read_text(encoding="utf-8").splitlines()[1:])
        + "\n",
        encoding="utf-8",
    )
    evidence = load_time_key_fixture(FIXTURES / "futu_time_key_start.json")
    provider = CSVProvider(combined, load_phase1_actions(FIXTURES / "corporate_actions.json"), evidence)
    assert len(provider.fetch_30m("QQQ", date(2024, 11, 27), date(2024, 11, 29))) == 20
    request = BuildDatasetRequest("QQQ", date(2024, 11, 27), date(2024, 11, 29), tmp_path / "data" / "phase1", FIXTURES / "futu_time_key_start.json")
    result = build_phase1_dataset(request, provider, XNYSCalendar())
    assert {path.name for path in result.destination.iterdir()} == {
        "bars_30m.csv", "bars_60m.csv", "daily.csv", "corporate_actions.json", "manifest.json"
    }
    manifest = json.loads((result.destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["row_counts"]["bars_30m.csv"] == 20
    assert manifest["row_counts"]["bars_60m.csv"] == 6
    assert manifest["row_counts"]["daily.csv"] == 2
    assert manifest["row_counts"]["corporate_actions.json"] == 2
    assert manifest["early_close_60m_policy"] == "EXCLUDE_FROM_60M_SEQUENCE"
    assert manifest["quality_status"] == "VALID"


def test_quality_failure_blocks_every_published_output(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text((FIXTURES / "normal_session_2024-11-27.csv").read_text(encoding="utf-8").replace("502", "0", 1), encoding="utf-8")
    evidence = load_time_key_fixture(FIXTURES / "futu_time_key_start.json")
    provider = CSVProvider(bad, load_phase1_actions(FIXTURES / "corporate_actions.json"), evidence)
    request = BuildDatasetRequest("QQQ", date(2024, 11, 27), date(2024, 11, 27), tmp_path / "data" / "phase1", FIXTURES / "futu_time_key_start.json")
    with pytest.raises(DataQualityFailedError):
        build_phase1_dataset(request, provider, XNYSCalendar())
    assert not (request.output_root / "datasets").exists()
```

- [ ] **Step 6: Run offline acceptance and complete regression verification**

Run: `python -m pytest tests/phase1_data/test_phase1_acceptance.py -q`

Expected: PASS; the combined ordinary/early-close CSV provider returns exactly 20 rows before orchestration, then publishes 20 30-minute rows, 6 strict 60-minute rows, 2 daily rows, corporate actions, and a valid manifest without network access.

Run: `python -m pytest tests/phase1_data -q`

Expected: all Phase 1 unit and acceptance tests PASS without network access.

Run: `python -m pytest tests -q`

Expected: all legacy and Phase 1 tests PASS; no test is removed or weakened.

Run: `python -m tv_quant.cli --help`

Expected: exit 0; legacy help lists `download` and `backtest` only.

Run: `python -m tv_quant.phase1_data.cli --help`

Expected: exit 0; Phase 1 help lists `validate-time-key` and `build` only.

Run: `git diff --check`

Expected: exit 0 with no whitespace errors.

- [ ] **Step 7: Commit acceptance coverage and documentation**

```bash
git add src/tv_quant/phase1_data/__init__.py tests/phase1_data/test_public_contract.py tests/phase1_data/test_phase1_acceptance.py docs/phase1-data-contract.md
git commit -m "Document and verify phase 1 data pipeline"
```

## Requirement-to-Test Acceptance Matrix

| Frozen Phase 1 requirement | Owning task | Concrete evidence |
|---|---:|---|
| Schema, raw/research fields, and time invariants | 1 | frozen fields; aware NY/UTC, duration, same-instant, session-date, and naive rejection tests |
| XNYS, New York/UTC, DST | 1, 2 | ordinary, closed day, early close, both DST boundaries, schedule hash |
| TEST versus production Futu time evidence | 3 | TEST offline pass/Futu reject; unverified and missing raw hash reject; separate manual gate |
| Bare symbol/provider code mapping | 3, 9, 10 | five-symbol mapping, CSV mismatch rejection, and 20-row acceptance read |
| RTH and ordinary 13-bar completeness | 4 | exact expected-start comparison plus pre/post filtering |
| Early-close count and boundaries | 4 | 7-bar 09:30–13:00 pass and count/bounds failures |
| OHLCV and split-factor quality | 5 | parameterized finite, positive, range, volume, and factor tests |
| Split event verification and dual hashes | 3, 6, 8 | supplier ratio inversion, raw-response hash, fetched-time-invariant content identity, reorder/change tests |
| Raw immutability and research adjustment | 6 | 2-for-1, cumulative factor, volume, effective-date, dividend tests |
| Strict 60-minute aggregation | 7 | independent raw/research OHLCV, six pairs, missing component and tail exclusion |
| Same-source daily aggregation | 7 | normal/early-close daily OHLCV and mixed-source rejection |
| Manifest, dataset SHA, calendar metadata | 8 | mandatory fields, repeated-raw identity, fetched-time invariance, and content-sensitive identity |
| Manifest-truth atomic publication | 8 | exact files, all recomputed hashes/ID/destination, tampering faults, immutable destination, rename failure |
| Quality/action/downstream error mapping | 8, 9, 10 | manifest gate, every frozen CLI exception code, and no-output acceptance test |
| Legacy directory and CLI isolation | 9, 10 | parser rejection, output-root validation, and both help commands |
| Public API and operator contract | 10 | intentional `__all__`/docs red, focused green, then network-free acceptance |

## Independent Review Finding Closure

| Finding | Closure in this revision | Verification anchor |
|---|---|---|
| PLAN-H-01 | Separates `TEST` and `PRODUCTION_CAPTURE`; freezes all evidence fields; Futu rejects TEST/unverified/missing-hash evidence; manual live confirmation is distinct from structural validation. | Task 3 offline rejection tests and manual integration gate; Task 10 documentation wording |
| PLAN-H-02 | Stores bare internal `symbol` and separate provider `provider_code`; freezes reversible mapping and mismatch rejection. | Tasks 1, 3, 4, 7; Task 10 asserts 20 combined CSV rows |
| PLAN-H-03 | Installs the edited requirements and prints the resolved version before calendar tests. | Task 2 Step 4 expects exactly `4.13.2` |
| PLAN-H-04 | Creates a dedicated helper module and removes test-to-test imports. | Task 4 helper code and staged-file list; Tasks 5–7 imports |
| PLAN-H-05 | Splits deterministic action-content hash, raw-response hash, and fetched audit time; dataset identity excludes fetched time. | Tasks 6 and 8 invariance/sensitivity tests |
| PLAN-H-06 | Treats staged manifest as publication truth and verifies schema, statuses, exact files, file hashes, dataset hash/ID, and destination. | Task 8 five fault modes plus rename-failure preservation |
| PLAN-H-07 | Freezes exit 6 for publication/atomic/existing destination and exit 4 for calendar/data/source/aggregation failures. | Task 9 parameterized exception-to-exit test |
| PLAN-H-08 | Enforces aware NY/UTC types, matching instants, strict 30/60-minute duration, ordering, and session-date equality. | Task 1 model constructors and DST/naive/mismatch tests |
| PLAN-H-09 | Uses the five-symbol allow-list throughout; Task 10 red is isolated to missing public exports/docs, followed by green and acceptance. | Tasks 1, 9, and 10 |

## Final Acceptance Commands

Implementation is complete only after all commands below succeed in this order:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -m pytest tests/phase1_data -q
python -m pytest tests -q
python -m tv_quant.cli --help
python -m tv_quant.phase1_data.cli --help
git diff --check
git status --short
git log --oneline --decorate -12
```

Expected results:

- Phase 1 tests pass offline.
- The complete suite passes without deleting or weakening legacy tests.
- Legacy and Phase 1 CLIs expose disjoint command sets.
- No runtime dataset, report, `.env`, API secret, `.superpowers/`, or `.worktrees/` content is staged.
- The ten implementation commits are visible and each task is independently reviewable.

## Plan Self-Review Record

1. **Scope:** Tasks cover only Phase 1 data-contract work; strategy, execution, broker, TradingView, and Phase 2+ concerns remain excluded.
2. **Symbols:** `QQQ`, `SPY`, `IWM`, `RSP`, and `DIA` are the single allow-list used by models, adapters, requests, CLI, tests, and docs.
3. **Time evidence:** TEST and PRODUCTION_CAPTURE have distinct permissions; structural validation is never described as proof of live vendor semantics.
4. **Time types:** Session, normalized, 30-minute, and 60-minute records enforce aware New York/UTC fields, matching instants, positive exact durations, and correct session dates.
5. **Provider identity:** Bare symbols and provider codes remain separate and mismatch tests block accidental interchange.
6. **Dependency order:** The pinned calendar package is installed and its runtime version is printed before its tests run.
7. **Test isolation:** Shared factories live only in `tests/phase1_data/helpers.py`; no test module imports another test module.
8. **Corporate-action identity:** Content, raw-response, and fetch-audit concepts are separate; fetched time cannot change deterministic data identity.
9. **Publication truth:** Atomic publish trusts only a parsed and recomputed staged manifest, rejects missing/extra/tampered content and wrong destinations, and preserves prior datasets on rename failure.
10. **CLI closure:** Every expected provider, time, quality, calendar, contract, source, aggregation, action, and publication exception has a documented nonzero code; no domain error relies on exit 1.
11. **Red/green integrity:** Each task has a focused red reason and green verification; Task 10's red is specifically public exports/docs, then public green, then offline end-to-end acceptance.
12. **Safety and reviewability:** Legacy files remain untouched, secrets and live orders are prohibited, outputs are immutable, all tests plus `git diff --check` are required, and each implementation task has one reviewable local commit.
