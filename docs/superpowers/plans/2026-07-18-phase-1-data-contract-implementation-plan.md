# Phase 1 Data Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a trustworthy, deterministic, auditable Phase 1 data foundation that converts unadjusted Futu 30-minute US bars into validated RTH 30-minute, strict 60-minute research, and same-source daily datasets with immutable manifests.

**Architecture:** Keep the existing `tv_quant.cli` daily EMA baseline operational and untouched. Add an isolated `tv_quant.phase1_data` package whose provider adapters feed immutable typed records through calendar normalization, session and OHLCV quality gates, corporate-action adjustment, aggregation, manifest construction, and an atomic versioned publisher. The new CLI is invoked only as `python -m tv_quant.phase1_data.cli`, publishes only under `data/phase1/datasets/<dataset_id>/`, and never falls back from Futu to yfinance or the legacy daily pipeline.

**Tech Stack:** Python 3.12, pandas 3.0.3, NumPy 2.5.1, pytest 9.1.1, Futu API 10.9.x, `exchange-calendars==4.13.2`, `zoneinfo`, dataclasses, pathlib, hashlib, JSON, CSV.

**Primary implementation references:** [`exchange-calendars` 4.13.2 on PyPI](https://pypi.org/project/exchange_calendars/), [Futu historical candlestick API](https://openapi.futunn.com/futu-api-doc/en/quote/request-history-kline.html), and [Futu adjustment-factor API](https://openapi.futunn.com/futu-api-doc/en/quote/get-rehab.html). These references define dependency/API vocabulary; the frozen design and checked fixtures define system behavior.

## Global Constraints

- Authoritative design baseline: commit `28a234d` and `docs/superpowers/specs/2026-07-18-quant-swing-research-system-design.md`.
- Scope is Implementation Phase 1 only: schemas, XNYS calendar, 30-minute Futu RTH data, raw/research fields, corporate actions, daily and strict 60-minute aggregation, Data Manifest, hashing, publication, and isolated CLI.
- Phase 2 and later strategy logic is excluded: EMA, ATR, volatility, pivot, pullback, recovery, entries, exits, stops, positions, costs, performance metrics, parameter search, Walk-forward, Locked OOS, external ETF validation, TradingView, options, portfolio logic, paper trading, and live trading.
- Internal instants are timezone-aware UTC; session rules are calculated in `America/New_York` with XNYS. Fixed UTC offsets are prohibited.
- An ordinary complete XNYS session contains 13 half-hour bars beginning 09:30 through 15:30 local. An early close uses `(session_close - session_open) / 30 minutes`; 09:30–13:00 contains 7 bars.
- Early-close sessions publish 30-minute and daily data but publish no 60-minute research bars; manifest policy is exactly `EXCLUDE_FROM_60M_SEQUENCE`.
- Futu `time_key` meaning is accepted only from a checked-in verified fixture. Internal timestamps always represent bar start.
- Futu 30-minute requests use `KLType.K_30M`, `AuType.NONE`, and no extended-hours request. Futu failure is explicit and cannot trigger another provider.
- Futu's documented `split_ratio` is vendor-oriented; the adapter converts it to the design contract `new_shares / old_shares` by `Decimal(1) / vendor_split_ratio`.
- Raw OHLCV is immutable. Research OHLC is divided by cumulative future verified split factors, research volume is multiplied by the same factors, and dividends never alter research fields.
- Every blocking data error produces `DATA_QUALITY_FAILED` or `DATA_ACTIONS_UNVERIFIED`, prevents publication, and returns a nonzero CLI exit code.
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
- `src/tv_quant/phase1_data/corporate_actions.py`: canonical corporate-action hash and split adjustment.
- `src/tv_quant/phase1_data/aggregation.py`: same-source daily aggregation and strict normal-session 60-minute aggregation.
- `src/tv_quant/phase1_data/manifest.py`: canonical dataset identity and `DataManifest` construction.
- `src/tv_quant/phase1_data/storage.py`: canonical serialization, SHA-256 helpers, staging validation, and atomic immutable publication.
- `src/tv_quant/phase1_data/pipeline.py`: deterministic orchestration and downstream quality gates.
- `src/tv_quant/phase1_data/cli.py`: isolated `validate-time-key` and `build` commands with fixed exit codes.

### New tests and fixtures

- `tests/phase1_data/test_models.py`
- `tests/phase1_data/test_calendar.py`
- `tests/phase1_data/test_futu.py`
- `tests/phase1_data/test_sessions.py`
- `tests/phase1_data/test_quality.py`
- `tests/phase1_data/test_corporate_actions.py`
- `tests/phase1_data/test_aggregation.py`
- `tests/phase1_data/test_manifest_storage.py`
- `tests/phase1_data/test_pipeline_cli.py`
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
├── staging/<run_id>/
│   ├── bars_30m.csv
│   ├── bars_60m.csv
│   ├── daily.csv
│   ├── corporate_actions.json
│   └── manifest.json
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
    def fetch_corporate_actions(self, symbol: str, start: date, end: date) -> tuple[CorporateAction, ...]: ...

class TradingCalendar(Protocol):
    library_name: str
    library_version: str
    def sessions(self, start: date, end: date) -> tuple[SessionSchedule, ...]: ...
    def session(self, session_date: date) -> SessionSchedule: ...
    def schedule_hash(self, start: date, end: date) -> str: ...

def normalize_futu_timestamp(source_timestamp: str, semantics: TimeKeySemantics) -> NormalizedTimestamp: ...
def filter_rth_bars(bars: Sequence[Bar30mRecord], schedule: SessionSchedule) -> tuple[Bar30mRecord, ...]: ...
def validate_30m_session(bars: Sequence[Bar30mRecord], schedule: SessionSchedule) -> SessionValidationResult: ...
def validate_ohlcv(bars: Sequence[Bar30mRecord]) -> DataQualityResult: ...
def validate_split_factors(bars: Sequence[Bar30mRecord]) -> DataQualityResult: ...
def apply_split_adjustment(bars: Sequence[Bar30mRecord], actions: Sequence[CorporateAction]) -> tuple[Bar30mRecord, ...]: ...
def aggregate_daily_bars(bars: Sequence[Bar30mRecord]) -> tuple[DailyBarRecord, ...]: ...
def aggregate_60m_research_bars(bars: Sequence[Bar30mRecord], schedule: SessionSchedule) -> tuple[Bar60mRecord, ...]: ...
def build_data_manifest(request: ManifestRequest) -> DataManifest: ...
def calculate_file_sha256(path: str | Path) -> str: ...
def calculate_dataset_sha256(files: Mapping[str, bytes]) -> str: ...
def atomic_write_dataset(destination: Path, files: Mapping[str, bytes], quality: DataQualityResult, actions_status: DataStatus) -> Path: ...
```

## Task 1: Freeze schemas, enums, and error states

**Files:**
- Create: `src/tv_quant/phase1_data/__init__.py`
- Create: `src/tv_quant/phase1_data/models.py`
- Create: `src/tv_quant/phase1_data/errors.py`
- Create: `tests/phase1_data/test_models.py`

**Interfaces:**
- Consumes: Python standard-library `date`, `datetime`, `Decimal`, `Enum`, and frozen dataclasses.
- Produces: `DataStatus`, `DataWarning`, `TimeKeySemantics`, `EarlyClose60mPolicy`, `CorporateActionType`, `SessionSchedule`, `NormalizedTimestamp`, `Bar30mRecord`, `Bar60mRecord`, `DailyBarRecord`, `CorporateAction`, `DataQualityResult`, `SessionValidationResult`, `ManifestRequest`, `DataManifest`, and the complete Phase 1 exception hierarchy.

- [ ] **Step 1: Write the failing schema tests**

```python
# tests/phase1_data/test_models.py
from dataclasses import FrozenInstanceError, fields
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from tv_quant.phase1_data.models import (
    Bar30mRecord, CorporateAction, CorporateActionType, DataQualityResult,
    DataStatus, EarlyClose60mPolicy, TimeKeySemantics,
)


def test_bar30m_contract_is_frozen_and_contains_raw_and_research_fields():
    names = {field.name for field in fields(Bar30mRecord)}
    assert names == {
        "source_timestamp", "bar_start_local", "bar_end_local", "bar_start_utc",
        "bar_end_utc", "session_date", "is_regular_session", "is_early_close",
        "source", "symbol", "raw_open", "raw_high", "raw_low", "raw_close",
        "raw_volume", "research_open", "research_high", "research_low",
        "research_close", "research_volume", "split_factor_t",
    }
    bar = Bar30mRecord(
        "2024-11-27 09:30:00", datetime(2024, 11, 27, 9, 30),
        datetime(2024, 11, 27, 10, 0), datetime(2024, 11, 27, 14, 30, tzinfo=timezone.utc),
        datetime(2024, 11, 27, 15, 0, tzinfo=timezone.utc), date(2024, 11, 27),
        True, False, "FUTU", "QQQ", Decimal("500"), Decimal("502"),
        Decimal("499"), Decimal("501"), Decimal("1000"), Decimal("500"),
        Decimal("502"), Decimal("499"), Decimal("501"), Decimal("1000"), Decimal("1"),
    )
    with pytest.raises(FrozenInstanceError):
        bar.raw_close = Decimal("0")


def test_exact_machine_states_and_split_definition_are_frozen():
    assert {state.value for state in DataStatus} == {
        "VALID", "DATA_QUALITY_FAILED", "DATA_ACTIONS_UNVERIFIED"
    }
    assert TimeKeySemantics.BAR_START.value == "BAR_START"
    assert TimeKeySemantics.BAR_END.value == "BAR_END"
    assert EarlyClose60mPolicy.EXCLUDE.value == "EXCLUDE_FROM_60M_SEQUENCE"
    action = CorporateAction(
        "FUTU", "QQQ", CorporateActionType.SPLIT, date(2022, 6, 6),
        Decimal("2"), datetime(2024, 1, 1, tzinfo=timezone.utc), "a" * 64, True,
    )
    assert action.ratio_new_over_old == Decimal("2")


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
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Mapping


class DataStatus(StrEnum):
    VALID = "VALID"
    DATA_QUALITY_FAILED = "DATA_QUALITY_FAILED"
    DATA_ACTIONS_UNVERIFIED = "DATA_ACTIONS_UNVERIFIED"


class DataWarning(StrEnum):
    ZERO_VOLUME_WARNING = "ZERO_VOLUME_WARNING"


class TimeKeySemantics(StrEnum):
    BAR_START = "BAR_START"
    BAR_END = "BAR_END"


class EarlyClose60mPolicy(StrEnum):
    EXCLUDE = "EXCLUDE_FROM_60M_SEQUENCE"


class CorporateActionType(StrEnum):
    SPLIT = "SPLIT"
    DIVIDEND = "DIVIDEND"


@dataclass(frozen=True)
class SessionSchedule:
    session_date: date
    open_local: datetime
    close_local: datetime
    open_utc: datetime
    close_utc: datetime
    is_early_close: bool
    expected_bar_count: int


@dataclass(frozen=True)
class NormalizedTimestamp:
    source_timestamp: str
    bar_start_local: datetime
    bar_end_local: datetime
    bar_start_utc: datetime
    bar_end_utc: datetime


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


@dataclass(frozen=True)
class Bar60mRecord:
    bar_start_local: datetime
    bar_end_local: datetime
    bar_start_utc: datetime
    bar_end_utc: datetime
    session_date: date
    source: str
    symbol: str
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
class DailyBarRecord:
    session_date: date
    source: str
    symbol: str
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
    corporate_action_sha256: str
    corporate_action_status: DataStatus
    time_key_semantics: TimeKeySemantics
    time_key_fixture_sha256: str


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
    corporate_action_sha256: str
    corporate_action_status: DataStatus
    time_key_semantics: TimeKeySemantics
    time_key_fixture_sha256: str


@dataclass(frozen=True)
class DatasetPaths:
    root: Path
    staging: Path
    datasets: Path
```

`src/tv_quant/phase1_data/__init__.py` re-exports the public names listed in **Frozen Public Interfaces** and does not import the CLI.

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
from datetime import date

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

- [ ] **Step 4: Run calendar tests and all regressions**

Run: `python -m pytest tests/phase1_data/test_calendar.py -q`

Expected: PASS with ordinary, holiday, weekend, early-close, DST-start, DST-end, and hash cases.

Run: `python -m pytest tests -q`

Expected: PASS.

- [ ] **Step 5: Commit the calendar boundary**

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
- Consumes: injected Futu quote context, `TimeKeySemantics`, `CorporateAction`, and unadjusted provider frames.
- Produces: `DataProvider`, `CSVProvider`, `FutuProvider`, `load_time_key_fixture(path)`, `normalize_futu_timestamp(source_timestamp, semantics)`, and supplier split events converted to `new_shares / old_shares`.

- [ ] **Step 1: Check in explicit semantic fixtures and failing tests**

File `tests/fixtures/phase1/futu_time_key_start.json`:

```json
{"fixture_version":"1","verified":true,"semantics":"BAR_START","source_timestamp":"2024-11-27 09:30:00","expected_bar_start_local":"2024-11-27T09:30:00-05:00","evidence":"captured K_30M row matched against the documented XNYS 09:30 open"}
```

File `tests/fixtures/phase1/futu_time_key_end.json`:

```json
{"fixture_version":"1","verified":true,"semantics":"BAR_END","source_timestamp":"2024-11-27 10:00:00","expected_bar_start_local":"2024-11-27T09:30:00-05:00","evidence":"controlled end-label fixture for conversion regression"}
```

File `tests/fixtures/phase1/futu_time_key_unverified.json`:

```json
{"fixture_version":"1","verified":false,"semantics":"BAR_START","source_timestamp":"2024-11-27 09:30:00","expected_bar_start_local":"2024-11-27T09:30:00-05:00","evidence":"not independently checked"}
```

```python
# tests/phase1_data/test_futu.py
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from tv_quant.phase1_data.errors import ProviderError, TimestampSemanticsUnverifiedError
from tv_quant.phase1_data.futu import FutuProvider, load_time_key_fixture, normalize_futu_timestamp
from tv_quant.phase1_data.models import TimeKeySemantics

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


def test_start_and_end_fixtures_normalize_to_the_same_internal_start():
    start_semantics, _ = load_time_key_fixture(FIXTURES / "futu_time_key_start.json")
    end_semantics, _ = load_time_key_fixture(FIXTURES / "futu_time_key_end.json")
    start = normalize_futu_timestamp("2024-11-27 09:30:00", start_semantics)
    end = normalize_futu_timestamp("2024-11-27 10:00:00", end_semantics)
    assert start.bar_start_local == end.bar_start_local
    assert start.bar_start_utc.isoformat() == "2024-11-27T14:30:00+00:00"
    assert start.source_timestamp != end.source_timestamp


def test_unverified_semantics_blocks_provider_use():
    with pytest.raises(TimestampSemanticsUnverifiedError, match="not verified"):
        load_time_key_fixture(FIXTURES / "futu_time_key_unverified.json")


def test_futu_provider_pages_unadjusted_30m_rth_requests_and_preserves_source_timestamp():
    first = pd.DataFrame({
        "code": ["US.QQQ"], "time_key": ["2024-11-27 09:30:00"],
        "open": [500.0], "high": [502.0], "low": [499.0], "close": [501.0], "volume": [1000],
    })
    context = QuoteContext([(0, first, b"next"), (0, first.assign(time_key="2024-11-27 10:00:00"), None)], pd.DataFrame())
    provider = FutuProvider(context, FIXTURES / "futu_time_key_start.json", ret_ok=0, k_30m="K_30M", no_adjust="NONE", sleep=lambda _: None)
    bars = provider.fetch_30m("QQQ", date(2024, 11, 27), date(2024, 11, 27))
    assert bars["source_timestamp"].tolist() == ["2024-11-27 09:30:00", "2024-11-27 10:00:00"]
    assert [request["page_req_key"] for request in context.requests] == [None, b"next"]
    assert all(request["ktype"] == "K_30M" and request["autype"] == "NONE" for request in context.requests)
    assert all(request["extended_time"] is False for request in context.requests)


def test_vendor_split_ratio_is_inverted_to_new_shares_over_old_shares():
    rehab = pd.DataFrame({
        "ex_div_date": ["2022-06-06"], "split_base": [1.0], "split_ert": [2.0],
        "join_base": [0.0], "join_ert": [0.0], "split_ratio": [0.5],
    })
    context = QuoteContext([], rehab)
    provider = FutuProvider(context, FIXTURES / "futu_time_key_start.json", ret_ok=0, k_30m="K_30M", no_adjust="NONE", sleep=lambda _: None)
    action = provider.fetch_corporate_actions("QQQ", date(2020, 1, 1), date(2024, 1, 1))[0]
    assert action.ratio_new_over_old == Decimal("2")
    assert action.verified


def test_futu_failure_is_explicit_without_provider_fallback():
    context = QuoteContext([(1, "permission denied", None)], pd.DataFrame())
    provider = FutuProvider(context, FIXTURES / "futu_time_key_start.json", ret_ok=0, k_30m="K_30M", no_adjust="NONE", sleep=lambda _: None)
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

from .models import CorporateAction


class DataProvider(Protocol):
    source_name: str
    source_version: str
    def fetch_30m(self, symbol: str, start: date, end: date) -> pd.DataFrame: ...
    def fetch_corporate_actions(self, symbol: str, start: date, end: date) -> tuple[CorporateAction, ...]: ...


class CSVProvider:
    source_name = "CSV"
    source_version = "fixture/1"

    def __init__(self, bars_path: Path, actions: tuple[CorporateAction, ...]) -> None:
        self._bars_path = Path(bars_path)
        self._actions = actions

    def fetch_30m(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        frame = pd.read_csv(self._bars_path, dtype={"source_timestamp": str})
        selected = frame.loc[
            frame["symbol"].str.upper().eq(symbol.upper())
            & pd.to_datetime(frame["source_timestamp"]).dt.date.between(start, end)
        ]
        if selected.empty:
            raise ValueError(f"no CSV 30-minute rows for {symbol}")
        return selected.reset_index(drop=True)

    def fetch_corporate_actions(self, symbol: str, start: date, end: date) -> tuple[CorporateAction, ...]:
        return tuple(action for action in self._actions if action.symbol == symbol and start <= action.effective_date <= end)
```

`src/tv_quant/phase1_data/futu.py` must implement the following exact rules:

```python
NEW_YORK = ZoneInfo("America/New_York")


def load_time_key_fixture(path: str | Path) -> tuple[TimeKeySemantics, str]:
    raw = Path(path).read_bytes()
    payload = json.loads(raw)
    if payload.get("verified") is not True:
        raise TimestampSemanticsUnverifiedError(f"time_key fixture {path} is not verified")
    semantics = TimeKeySemantics(payload["semantics"])
    normalized = normalize_futu_timestamp(payload["source_timestamp"], semantics)
    if normalized.bar_start_local.isoformat() != payload["expected_bar_start_local"]:
        raise TimestampSemanticsUnverifiedError(f"time_key fixture {path} contradicts expected start")
    return semantics, hashlib.sha256(raw).hexdigest()


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
        self.time_key_semantics, self.time_key_fixture_sha256 = load_time_key_fixture(fixture_path)

    def fetch_30m(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        code = f"US.{symbol.upper()}"
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
            "symbol": symbol.upper(),
            "open": merged["open"], "high": merged["high"], "low": merged["low"],
            "close": merged["close"], "volume": merged["volume"],
        })

    def fetch_corporate_actions(
        self, symbol: str, start: date, end: date,
    ) -> tuple[CorporateAction, ...]:
        code = f"US.{symbol.upper()}"
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
        return tuple(actions)
```

The module imports `hashlib`, `json`, `time`, `date`, `datetime`, `timedelta`, `timezone`, `Decimal`, `Path`, `ZoneInfo`, pandas, `ProviderError`, `TimestampSemanticsUnverifiedError`, and the model types used above. Rows without positive split or join numerator/denominator pairs remain in the hashed source evidence but do not produce split adjustments.

- [ ] **Step 4: Run adapter tests and all regressions**

Run: `python -m pytest tests/phase1_data/test_futu.py -q`

Expected: PASS, including both timestamp meanings, unverified rejection, pagination, unadjusted K_30M arguments, source preservation, supplier ratio inversion, and explicit failure.

Run: `python -m pytest tests -q`

Expected: PASS.

- [ ] **Step 5: Commit providers and evidence fixtures**

```bash
git add src/tv_quant/phase1_data/providers.py src/tv_quant/phase1_data/futu.py tests/phase1_data/test_futu.py tests/fixtures/phase1/futu_time_key_start.json tests/fixtures/phase1/futu_time_key_end.json tests/fixtures/phase1/futu_time_key_unverified.json
git commit -m "Add verified Futu 30 minute adapter"
```

## Task 4: Filter RTH and validate ordinary and early-close sessions

**Files:**
- Create: `src/tv_quant/phase1_data/sessions.py`
- Create: `tests/phase1_data/test_sessions.py`
- Create: `tests/fixtures/phase1/normal_session_2024-11-27.csv`
- Create: `tests/fixtures/phase1/early_close_2024-11-29.csv`

**Interfaces:**
- Consumes: `Bar30mRecord` sequences and one `SessionSchedule` from Task 2.
- Produces: `filter_rth_bars(...) -> tuple[Bar30mRecord, ...]` and `validate_30m_session(...) -> SessionValidationResult`.

- [ ] **Step 1: Create deterministic session fixture generation and failing tests**

The two CSV fixtures use these exact columns and values. `normal_session_2024-11-27.csv` has starts from `2024-11-27 09:30:00` through `15:30:00` in 30-minute increments; `early_close_2024-11-29.csv` has starts from `09:30:00` through `12:30:00`. Every row uses `US.QQQ`, OHLC `500,502,499,501`, volume `1000`, and includes no premarket or postmarket row.

```python
# tests/phase1_data/test_sessions.py
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tv_quant.phase1_data.calendar import XNYSCalendar
from tv_quant.phase1_data.models import Bar30mRecord, DataStatus
from tv_quant.phase1_data.sessions import filter_rth_bars, validate_30m_session


def bar(start_local: datetime, *, minutes=30, source="FUTU") -> Bar30mRecord:
    end_local = start_local + timedelta(minutes=minutes)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)
    one = Decimal("1")
    return Bar30mRecord(
        start_local.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"), start_local,
        end_local, start_utc, end_utc, start_local.date(), True, False, source, "QQQ",
        Decimal("500"), Decimal("502"), Decimal("499"), Decimal("501"), Decimal("1000"),
        Decimal("500"), Decimal("502"), Decimal("499"), Decimal("501"), Decimal("1000"), one,
    )


def scheduled_bars(session_date: date) -> tuple[Bar30mRecord, ...]:
    schedule = XNYSCalendar().session(session_date)
    return tuple(bar(schedule.open_local + index * timedelta(minutes=30)) for index in range(schedule.expected_bar_count))


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
    pre = replace(bar(schedule.open_local - timedelta(minutes=30)), is_regular_session=False)
    post = replace(bar(schedule.close_local), is_regular_session=False)
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
git add src/tv_quant/phase1_data/sessions.py tests/phase1_data/test_sessions.py tests/fixtures/phase1/normal_session_2024-11-27.csv tests/fixtures/phase1/early_close_2024-11-29.csv
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
from tests.phase1_data.test_sessions import scheduled_bars


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
- Produces: `hash_corporate_actions(actions) -> str` and `apply_split_adjustment(bars, actions) -> tuple[Bar30mRecord, ...]`.

- [ ] **Step 1: Add the canonical event fixture and failing adjustment tests**

```json
[
  {"source":"FUTU","symbol":"QQQ","action_type":"SPLIT","effective_date":"2022-06-06","ratio_new_over_old":"2","fetched_at_utc":"2024-01-01T00:00:00+00:00","source_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","verified":true},
  {"source":"FUTU","symbol":"QQQ","action_type":"DIVIDEND","effective_date":"2023-12-20","ratio_new_over_old":"1","fetched_at_utc":"2024-01-01T00:00:00+00:00","source_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","verified":true}
]
```

```python
# tests/phase1_data/test_corporate_actions.py
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from tv_quant.phase1_data.corporate_actions import apply_split_adjustment, hash_corporate_actions
from tv_quant.phase1_data.errors import CorporateActionsUnverifiedError
from tv_quant.phase1_data.models import CorporateAction, CorporateActionType
from tests.phase1_data.test_sessions import scheduled_bars


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


def test_action_hash_is_canonical_and_changes_with_event_content():
    original = (action(CorporateActionType.SPLIT, date(2024, 1, 3), "2"),)
    assert hash_corporate_actions(original) == hash_corporate_actions(tuple(reversed(original)))
    changed = (replace(original[0], ratio_new_over_old=Decimal("3")),)
    assert hash_corporate_actions(original) != hash_corporate_actions(changed)
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
from dataclasses import asdict, replace
from decimal import Decimal
from typing import Sequence

from .errors import CorporateActionsUnverifiedError
from .models import Bar30mRecord, CorporateAction, CorporateActionType


def _canonical_actions(actions: Sequence[CorporateAction]) -> bytes:
    rows = []
    for action in sorted(actions, key=lambda item: (item.symbol, item.effective_date, item.action_type.value)):
        row = asdict(action)
        row["action_type"] = action.action_type.value
        row["effective_date"] = action.effective_date.isoformat()
        row["ratio_new_over_old"] = str(action.ratio_new_over_old)
        row["fetched_at_utc"] = action.fetched_at_utc.isoformat()
        rows.append(row)
    return json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")


def hash_corporate_actions(actions: Sequence[CorporateAction]) -> str:
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

Expected: PASS for no split, 2-for-1, cumulative factors, effective-date boundary, raw immutability, volume adjustment, unverified block, hash change, and dividend exclusion.

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
from tests.phase1_data.test_sessions import scheduled_bars


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
    return next(iter(sources)), next(iter(symbols))


def aggregate_daily_bars(bars: Sequence[Bar30mRecord]) -> tuple[DailyBarRecord, ...]:
    grouped: dict[object, list[Bar30mRecord]] = defaultdict(list)
    for bar in bars:
        grouped[bar.session_date].append(bar)
    result: list[DailyBarRecord] = []
    for session_date in sorted(grouped):
        items = sorted(grouped[session_date], key=lambda item: item.bar_start_utc)
        source, symbol = _one_source_and_symbol(items)
        result.append(DailyBarRecord(
            session_date, source, symbol,
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
    source, symbol = _one_source_and_symbol(items)
    result: list[Bar60mRecord] = []
    for index in range(0, 12, 2):
        first, second = items[index:index + 2]
        if first.bar_end_utc != second.bar_start_utc:
            raise AggregationError("60-minute component bar is missing")
        result.append(Bar60mRecord(
            first.bar_start_local, second.bar_end_local, first.bar_start_utc, second.bar_end_utc,
            schedule.session_date, source, symbol,
            first.raw_open, max(first.raw_high, second.raw_high), min(first.raw_low, second.raw_low), second.raw_close, first.raw_volume + second.raw_volume,
            first.research_open, max(first.research_high, second.research_high), min(first.research_low, second.research_low), second.research_close, first.research_volume + second.research_volume,
        ))
    return tuple(result)
```

- [ ] **Step 4: Run focused and regression tests**

Run: `python -m pytest tests/phase1_data/test_aggregation.py -q`

Expected: PASS for raw/research OHLCV, six-pair construction, tail exclusion, cross-session rejection, missing component, daily ordinary/early-close aggregation, and source mixing rejection.

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
- Consumes: canonical output bytes, `ManifestRequest`, final quality result, and corporate-action status.
- Produces: `calculate_file_sha256`, `calculate_dataset_sha256`, `build_data_manifest`, `manifest_json_bytes`, and `atomic_write_dataset`.

- [ ] **Step 1: Add failing manifest, hash, and failure-injection tests**

```python
# tests/phase1_data/test_manifest_storage.py
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from tv_quant.phase1_data.errors import AtomicWriteError, PublicationBlockedError
from tv_quant.phase1_data.manifest import build_data_manifest, manifest_json_bytes
from tv_quant.phase1_data.models import (
    DataQualityResult, DataStatus, EarlyClose60mPolicy, ManifestRequest,
    TimeKeySemantics,
)
from tv_quant.phase1_data.storage import (
    atomic_write_dataset, calculate_dataset_sha256, calculate_file_sha256,
)


def request(dataset_hash="1" * 64, action_hash="2" * 64, schedule_hash="3" * 64):
    return ManifestRequest(
        source="FUTU", source_version="10.9", generated_at_utc=datetime(2026, 7, 18, tzinfo=timezone.utc),
        timezone="UTC", start_date=date(2024, 11, 27), end_date=date(2024, 11, 29),
        row_counts={"bars_30m.csv": 20, "bars_60m.csv": 6, "daily.csv": 2},
        fields={"bars_30m.csv": ("bar_start_utc", "raw_open", "research_open")},
        file_hashes={"bars_30m.csv": "4" * 64}, dataset_sha256=dataset_hash,
        quality_status=DataStatus.VALID, warnings=(), calendar_library="exchange_calendars",
        calendar_library_version="4.13.2", calendar_schedule_hash=schedule_hash,
        early_close_60m_policy=EarlyClose60mPolicy.EXCLUDE,
        corporate_action_sha256=action_hash, corporate_action_status=DataStatus.VALID,
        time_key_semantics=TimeKeySemantics.BAR_START, time_key_fixture_sha256="5" * 64,
    )


def test_manifest_contains_every_mandatory_field_and_deterministic_identity():
    manifest = build_data_manifest(request())
    assert manifest.schema_version == "phase1-data-contract/1.0.0"
    assert manifest.dataset_id.startswith("phase1-")
    assert manifest.calendar_library == "exchange_calendars"
    assert manifest.calendar_library_version == "4.13.2"
    assert manifest.calendar_schedule_hash == "3" * 64
    assert manifest.early_close_60m_policy.value == "EXCLUDE_FROM_60M_SEQUENCE"
    assert build_data_manifest(request()).dataset_id == manifest.dataset_id
    assert build_data_manifest(request(dataset_hash="9" * 64)).dataset_id != manifest.dataset_id
    assert build_data_manifest(request(action_hash="8" * 64)).dataset_id != manifest.dataset_id


def test_file_and_dataset_hashes_are_stable_and_content_sensitive(tmp_path):
    file = tmp_path / "bars.csv"
    file.write_bytes(b"a,b\n1,2\n")
    assert calculate_file_sha256(file) == calculate_file_sha256(file)
    first = calculate_dataset_sha256({"bars.csv": file.read_bytes(), "daily.csv": b"x\n"})
    assert first == calculate_dataset_sha256({"daily.csv": b"x\n", "bars.csv": file.read_bytes()})
    assert first != calculate_dataset_sha256({"bars.csv": b"a,b\n1,3\n", "daily.csv": b"x\n"})


def test_atomic_publish_succeeds_only_after_staged_hash_validation(tmp_path):
    destination = tmp_path / "datasets" / "phase1-abc"
    files = {"bars_30m.csv": b"a,b\n1,2\n", "manifest.json": manifest_json_bytes(build_data_manifest(request()))}
    result = atomic_write_dataset(destination, files, DataQualityResult(DataStatus.VALID, (), ()), DataStatus.VALID)
    assert result == destination
    assert (destination / "bars_30m.csv").read_bytes() == files["bars_30m.csv"]
    assert not list(destination.parent.glob(".phase1-abc.tmp-*"))


@pytest.mark.parametrize("quality,actions", [
    (DataQualityResult(DataStatus.DATA_QUALITY_FAILED, ("bad bar",), ()), DataStatus.VALID),
    (DataQualityResult(DataStatus.VALID, (), ()), DataStatus.DATA_ACTIONS_UNVERIFIED),
])
def test_blocking_status_never_publishes(tmp_path, quality, actions):
    with pytest.raises(PublicationBlockedError):
        atomic_write_dataset(tmp_path / "datasets" / "blocked", {"x": b"1"}, quality, actions)
    assert not (tmp_path / "datasets" / "blocked").exists()


def test_existing_valid_dataset_is_never_overwritten(tmp_path):
    destination = tmp_path / "datasets" / "phase1-existing"
    destination.mkdir(parents=True)
    valid = destination / "bars_30m.csv"
    valid.write_bytes(b"old-valid")
    with pytest.raises(FileExistsError):
        atomic_write_dataset(destination, {"bars_30m.csv": b"new"}, DataQualityResult(DataStatus.VALID, (), ()), DataStatus.VALID)
    assert valid.read_bytes() == b"old-valid"


def test_replace_failure_cleans_staging_and_preserves_other_datasets(tmp_path, monkeypatch):
    other = tmp_path / "datasets" / "phase1-old"
    other.mkdir(parents=True)
    (other / "manifest.json").write_bytes(b"old")
    monkeypatch.setattr("tv_quant.phase1_data.storage.os.replace", lambda *_: (_ for _ in ()).throw(OSError("disk fault")))
    with pytest.raises(AtomicWriteError, match="disk fault"):
        atomic_write_dataset(tmp_path / "datasets" / "phase1-new", {"x": b"1"}, DataQualityResult(DataStatus.VALID, (), ()), DataStatus.VALID)
    assert (other / "manifest.json").read_bytes() == b"old"
    assert not list((tmp_path / "datasets").glob(".phase1-new.tmp-*"))
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

from .models import DataManifest, ManifestRequest


SCHEMA_VERSION = "phase1-data-contract/1.0.0"


def build_data_manifest(request: ManifestRequest) -> DataManifest:
    identity_input = {
        "schema_version": SCHEMA_VERSION,
        "dataset_sha256": request.dataset_sha256,
        "calendar_schedule_hash": request.calendar_schedule_hash,
        "corporate_action_sha256": request.corporate_action_sha256,
        "time_key_fixture_sha256": request.time_key_fixture_sha256,
        "early_close_60m_policy": request.early_close_60m_policy.value,
    }
    identity = hashlib.sha256(json.dumps(identity_input, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return DataManifest(SCHEMA_VERSION, f"phase1-{identity[:24]}", **asdict(request))


def manifest_json_bytes(manifest: DataManifest) -> bytes:
    payload = asdict(manifest)
    payload["generated_at_utc"] = manifest.generated_at_utc.isoformat()
    payload["start_date"] = manifest.start_date.isoformat()
    payload["end_date"] = manifest.end_date.isoformat()
    payload["quality_status"] = manifest.quality_status.value
    payload["warnings"] = [item.value for item in manifest.warnings]
    payload["early_close_60m_policy"] = manifest.early_close_60m_policy.value
    payload["corporate_action_status"] = manifest.corporate_action_status.value
    payload["time_key_semantics"] = manifest.time_key_semantics.value
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
```

```python
# src/tv_quant/phase1_data/storage.py
from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from pathlib import Path
from typing import Mapping

from .errors import AtomicWriteError, PublicationBlockedError
from .models import DataQualityResult, DataStatus


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
    quality: DataQualityResult,
    actions_status: DataStatus,
) -> Path:
    destination = Path(destination)
    if not quality.is_valid:
        raise PublicationBlockedError("DATA_QUALITY_FAILED prevents dataset publication")
    if actions_status is not DataStatus.VALID:
        raise PublicationBlockedError("DATA_ACTIONS_UNVERIFIED prevents dataset publication")
    if destination.exists():
        raise FileExistsError(f"immutable dataset already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.tmp-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        expected: dict[str, str] = {}
        for relative_name, content in files.items():
            target = staging / relative_name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            expected[relative_name] = hashlib.sha256(content).hexdigest()
        actual = {name: calculate_file_sha256(staging / name) for name in expected}
        if actual != expected:
            raise AtomicWriteError("staged dataset hash verification failed")
        os.replace(staging, destination)
    except Exception as error:
        shutil.rmtree(staging, ignore_errors=True)
        if isinstance(error, (AtomicWriteError, FileExistsError, PublicationBlockedError)):
            raise
        raise AtomicWriteError(str(error)) from error
    return destination
```

Add these lines to `.gitignore`:

```text
data/phase1/staging/
data/phase1/datasets/
```

- [ ] **Step 4: Run focused tests and full regression**

Run: `python -m pytest tests/phase1_data/test_manifest_storage.py -q`

Expected: PASS for mandatory fields, library/version/hash metadata, policy, stable and changing SHA-256, successful atomic replacement, blocking gates, immutable destination, and injected write failure.

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
    CorporateActionsUnverifiedError, DataQualityFailedError, ProviderError, PublicationBlockedError,
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


@pytest.mark.parametrize(
    ("error", "exit_code"),
    [
        (ProviderError("Futu failed"), EXIT_PROVIDER),
        (DataQualityFailedError("bad bars"), EXIT_QUALITY),
        (CorporateActionsUnverifiedError("bad actions"), EXIT_ACTIONS),
        (PublicationBlockedError("blocked"), EXIT_PUBLICATION),
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
from .corporate_actions import apply_split_adjustment, hash_corporate_actions
from .errors import CorporateActionsUnverifiedError, DataQualityFailedError
from .futu import normalize_futu_timestamp
from .manifest import build_data_manifest, manifest_json_bytes
from .models import (
    Bar30mRecord, Bar60mRecord, CorporateAction, DailyBarRecord, DataQualityResult,
    DataStatus, EarlyClose60mPolicy, ManifestRequest, TimeKeySemantics,
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
        if self.symbol not in {"SPY", "QQQ"}:
            raise ValueError("Phase 1 symbol must be SPY or QQQ")
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
    payload = []
    for action in sorted(actions, key=lambda item: (item.symbol, item.effective_date, item.action_type.value)):
        row = asdict(action)
        row["action_type"] = action.action_type.value
        row["effective_date"] = action.effective_date.isoformat()
        row["ratio_new_over_old"] = str(action.ratio_new_over_old)
        row["fetched_at_utc"] = action.fetched_at_utc.isoformat()
        payload.append(row)
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
            schedule.is_early_close, source, symbol, raw_open, raw_high, raw_low,
            raw_close, raw_volume, raw_open, raw_high, raw_low, raw_close, raw_volume,
            Decimal("1"),
        ))
    return tuple(records)


def build_phase1_dataset(
    request: BuildDatasetRequest,
    provider: DataProvider,
    calendar: TradingCalendar,
    fixture_semantics: TimeKeySemantics,
    fixture_hash: str,
) -> PipelineResult:
    schedules = calendar.sessions(request.start, request.end)
    frame = provider.fetch_30m(request.symbol, request.start, request.end)
    actions = provider.fetch_corporate_actions(request.symbol, request.start, request.end)
    if any(not action.verified for action in actions):
        raise CorporateActionsUnverifiedError("corporate action set contains an unverified event")
    records = _records_from_frame(frame, provider.source_name, request.symbol, schedules, fixture_semantics)
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
        row_counts={"bars_30m.csv": len(adjusted), "bars_60m.csv": len(bars_60m), "daily.csv": len(daily)},
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
        corporate_action_sha256=hash_corporate_actions(actions),
        corporate_action_status=DataStatus.VALID,
        time_key_semantics=fixture_semantics, time_key_fixture_sha256=fixture_hash,
    ))
    files["manifest.json"] = manifest_json_bytes(manifest)
    destination = request.output_root / "datasets" / manifest.dataset_id
    atomic_write_dataset(destination, files, quality, manifest.corporate_action_status)
    return PipelineResult(manifest.dataset_id, destination)
```

```python
# src/tv_quant/phase1_data/cli.py
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from .calendar import XNYSCalendar
from .errors import (
    CorporateActionsUnverifiedError, DataQualityFailedError, ProviderError,
    PublicationBlockedError, TimestampSemanticsUnverifiedError,
)
from .futu import FutuProvider, load_time_key_fixture
from .models import CorporateAction, CorporateActionType
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
    build.add_argument("--symbol", choices=("SPY", "QQQ"), required=True)
    build.add_argument("--start", type=date.fromisoformat, required=True)
    build.add_argument("--end", type=date.fromisoformat, required=True)
    build.add_argument("--provider", choices=("futu", "csv"), required=True)
    build.add_argument("--bars", type=Path)
    build.add_argument("--actions", type=Path)
    build.add_argument("--time-key-fixture", type=Path, required=True)
    build.add_argument("--output-root", type=Path, default=Path("data/phase1"))
    return parser


def _load_actions(path: Path) -> tuple[CorporateAction, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        CorporateAction(
            row["source"], row["symbol"], CorporateActionType(row["action_type"]),
            date.fromisoformat(row["effective_date"]), Decimal(row["ratio_new_over_old"]),
            datetime.fromisoformat(row["fetched_at_utc"]), row["source_sha256"],
            bool(row["verified"]),
        )
        for row in payload
    )


def _execute_build(args: argparse.Namespace) -> PipelineResult:
    semantics, fixture_hash = load_time_key_fixture(args.time_key_fixture)
    request = BuildDatasetRequest(
        args.symbol, args.start, args.end, args.output_root, args.time_key_fixture,
    )
    calendar = XNYSCalendar()
    if args.provider == "csv":
        if args.bars is None or args.actions is None:
            raise ValueError("csv provider requires --bars and --actions")
        provider = CSVProvider(args.bars, _load_actions(args.actions))
        return build_phase1_dataset(request, provider, calendar, semantics, fixture_hash)

    from futu import AuType, KLType, OpenQuoteContext, RET_OK

    context = OpenQuoteContext(host="127.0.0.1", port=11111)
    try:
        provider = FutuProvider(
            context, args.time_key_fixture, ret_ok=RET_OK,
            k_30m=KLType.K_30M, no_adjust=AuType.NONE,
        )
        return build_phase1_dataset(request, provider, calendar, semantics, fixture_hash)
    finally:
        context.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate-time-key":
            semantics, digest = load_time_key_fixture(args.fixture)
            print(f"{semantics.value} {digest}")
            return EXIT_OK
        result = _execute_build(args)
        print(result.destination)
        return EXIT_OK
    except (ProviderError, TimestampSemanticsUnverifiedError) as error:
        print(error, file=sys.stderr)
        return EXIT_PROVIDER
    except DataQualityFailedError as error:
        print(error, file=sys.stderr)
        return EXIT_QUALITY
    except CorporateActionsUnverifiedError as error:
        print(error, file=sys.stderr)
        return EXIT_ACTIONS
    except PublicationBlockedError as error:
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

Expected: PASS; legacy parser rejects `build`, Phase 1 paths reject `data/raw`, each blocking state has its fixed nonzero code, and successful output is an immutable dataset path.

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
- Create: `tests/phase1_data/test_phase1_acceptance.py`
- Create: `docs/phase1-data-contract.md`
- Modify: `src/tv_quant/phase1_data/__init__.py`

**Interfaces:**
- Consumes: checked-in CSV/action/time fixtures and all Phase 1 public interfaces.
- Produces: one network-free end-to-end proof, a documented operator contract, and final public exports. It does not download data or run a strategy.

- [ ] **Step 1: Add failing end-to-end acceptance tests**

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

FIXTURES = Path("tests/fixtures/phase1")


def actions_from_fixture():
    from datetime import datetime
    from decimal import Decimal
    from tv_quant.phase1_data.models import CorporateAction, CorporateActionType
    return tuple(
        CorporateAction(
            row["source"], row["symbol"], CorporateActionType(row["action_type"]),
            date.fromisoformat(row["effective_date"]), Decimal(row["ratio_new_over_old"]),
            datetime.fromisoformat(row["fetched_at_utc"]), row["source_sha256"], row["verified"],
        )
        for row in json.loads((FIXTURES / "corporate_actions.json").read_text(encoding="utf-8"))
    )


def test_normal_and_early_close_publish_expected_files_and_manifest(tmp_path):
    combined = tmp_path / "bars.csv"
    combined.write_text(
        (FIXTURES / "normal_session_2024-11-27.csv").read_text(encoding="utf-8").rstrip()
        + "\n"
        + "\n".join((FIXTURES / "early_close_2024-11-29.csv").read_text(encoding="utf-8").splitlines()[1:])
        + "\n",
        encoding="utf-8",
    )
    provider = CSVProvider(combined, actions_from_fixture())
    semantics, fixture_hash = load_time_key_fixture(FIXTURES / "futu_time_key_start.json")
    request = BuildDatasetRequest("QQQ", date(2024, 11, 27), date(2024, 11, 29), tmp_path / "data" / "phase1", FIXTURES / "futu_time_key_start.json")
    result = build_phase1_dataset(request, provider, XNYSCalendar(), semantics, fixture_hash)
    assert {path.name for path in result.destination.iterdir()} == {
        "bars_30m.csv", "bars_60m.csv", "daily.csv", "corporate_actions.json", "manifest.json"
    }
    manifest = json.loads((result.destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["row_counts"] == {"bars_30m.csv": 20, "bars_60m.csv": 6, "daily.csv": 2}
    assert manifest["early_close_60m_policy"] == "EXCLUDE_FROM_60M_SEQUENCE"
    assert manifest["quality_status"] == "VALID"


def test_quality_failure_blocks_every_published_output(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text((FIXTURES / "normal_session_2024-11-27.csv").read_text(encoding="utf-8").replace("502", "0", 1), encoding="utf-8")
    provider = CSVProvider(bad, actions_from_fixture())
    semantics, fixture_hash = load_time_key_fixture(FIXTURES / "futu_time_key_start.json")
    request = BuildDatasetRequest("QQQ", date(2024, 11, 27), date(2024, 11, 27), tmp_path / "data" / "phase1", FIXTURES / "futu_time_key_start.json")
    with pytest.raises(DataQualityFailedError):
        build_phase1_dataset(request, provider, XNYSCalendar(), semantics, fixture_hash)
    assert not (request.output_root / "datasets").exists()
```

- [ ] **Step 2: Run the acceptance test and confirm the incomplete integration failure**

Run: `python -m pytest tests/phase1_data/test_phase1_acceptance.py -q`

Expected: FAIL until record conversion, canonical serialization, manifest fields, and publication are fully connected.

- [ ] **Step 3: Complete public exports and operator documentation**

`src/tv_quant/phase1_data/__init__.py` must export every name under **Frozen Public Interfaces** and set `__all__` to that exact list. It must not export Futu SDK objects or import `cli.py`.

Create `docs/phase1-data-contract.md` with these exact operational sections:

1. `Scope and exclusions`: list Phase 1 contents and every Phase 2+ exclusion from Global Constraints.
2. `Data sources`: Futu unadjusted K_30M primary input, no silent fallback, Futu 30-minute history availability risk, and CSV only as an explicit test/import provider.
3. `Time contract`: XNYS, America/New_York localization, UTC storage, fixture gate, ordinary/early-close counts, and DST examples.
4. `Price contract`: immutable raw fields, split-only research fields, supplier ratio inversion, dividend exclusion, and action hash invalidation.
5. `Runtime layout`: the exact staging/datasets tree and immutable dataset-id usage.
6. `Commands`: `validate-time-key`, CSV build, and Futu build examples using only SPY or QQQ and no credentials.
7. `Exit codes`: 0 success, 2 arguments, 3 provider/time fixture, 4 quality, 5 actions, 6 publication.
8. `Legacy isolation`: existing daily download/backtest commands and `data/raw` remain separate and cannot be inputs to Phase 1.
9. `Manifest fields`: enumerate every `DataManifest` field and define dataset/file/calendar/action hashes.
10. `Residual risks`: Futu time semantics evidence, supplier history limits/revisions, corporate-action revisions, calendar-version changes, and 30-minute bars not proving tick-level paths.

- [ ] **Step 4: Run complete acceptance and regression verification**

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

- [ ] **Step 5: Commit acceptance coverage and documentation**

```bash
git add src/tv_quant/phase1_data/__init__.py tests/phase1_data/test_phase1_acceptance.py docs/phase1-data-contract.md
git commit -m "Document and verify phase 1 data pipeline"
```

## Requirement-to-Test Acceptance Matrix

| Frozen Phase 1 requirement | Owning task | Concrete evidence |
|---|---:|---|
| Schema and raw/research fields | 1 | frozen dataclass field equality and immutability test |
| XNYS, New York/UTC, DST | 2 | ordinary, closed day, early close, both DST boundaries, schedule hash |
| Futu K_30M adapter and time semantics | 3 | both fixture meanings, unverified rejection, request argument and pagination tests |
| RTH and ordinary 13-bar completeness | 4 | exact expected-start comparison plus pre/post filtering |
| Early-close count and boundaries | 4 | 7-bar 09:30–13:00 pass and count/bounds failures |
| OHLCV and split-factor quality | 5 | parameterized finite, positive, range, volume, and factor tests |
| Split event verification and hash | 3, 6 | supplier ratio inversion, unverified block, canonical hash change |
| Raw immutability and research adjustment | 6 | 2-for-1, cumulative factor, volume, effective-date, dividend tests |
| Strict 60-minute aggregation | 7 | independent raw/research OHLCV, six pairs, missing component and tail exclusion |
| Same-source daily aggregation | 7 | normal/early-close daily OHLCV and mixed-source rejection |
| Manifest, dataset SHA, calendar metadata | 8 | mandatory field and content-sensitive identity tests |
| Atomic write and old-file preservation | 8 | staged validation, immutable destination, and injected replace failure |
| Quality/action downstream blocking | 8, 9, 10 | publication gate, fixed CLI status codes, and no-output acceptance test |
| Legacy directory and CLI isolation | 9, 10 | parser rejection, output-root validation, and both help commands |

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

- **Spec coverage:** All 25 requested Phase 1 capabilities and test groups A–H map to Tasks 1–10 and the acceptance matrix. Phase 2+ strategy and execution logic is absent.
- **Completeness scan:** Every task names exact files, interfaces, test code, implementation code or a closed ordered implementation algorithm, commands, expected outcomes, and a local commit message.
- **Type consistency:** `Bar30mRecord`, `CorporateAction`, `DataQualityResult`, `SessionValidationResult`, `ManifestRequest`, `DataManifest`, provider/calendar protocols, and all pure-function signatures match the Frozen Public Interfaces section.
- **Safety:** The plan retains the current daily EMA pipeline, rejects provider mixing and unverified actions, publishes immutable version directories, and never stores credentials or contacts a broker.
- **Implementation correction captured:** Futu's supplier `split_ratio` orientation is inverted at the adapter boundary so the internal field always means `new_shares / old_shares`.
- **Dependency correction captured:** XNYS integration is pinned to `exchange-calendars==4.13.2`, and both library version and schedule hash are persisted in every manifest.
