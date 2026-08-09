from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import exchange_calendars as xcals
import pandas as pd

from tv_quant.data_quality import DataQualityError, validate_ohlcv


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    symbol: str
    expected_latest_session: date
    first_session: date | None
    last_session: date | None
    missing_sessions: tuple[date, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.errors and not self.missing_sessions


def latest_complete_xnys_session(as_of_utc: datetime) -> date:
    if as_of_utc.tzinfo is None or as_of_utc.utcoffset() != timedelta(0):
        raise ValueError("as_of_utc must be timezone-aware UTC")

    calendar = xcals.get_calendar("XNYS")
    as_of = pd.Timestamp(as_of_utc)
    candidate = calendar.date_to_session(as_of.date(), direction="previous")
    if as_of < calendar.session_close(candidate):
        candidate = calendar.previous_session(candidate)
    return candidate.date()


def assess_symbol_data(
    data: pd.DataFrame,
    symbol: str,
    as_of_utc: datetime,
) -> DataQualityReport:
    normalized_symbol = symbol.strip().upper()
    expected_latest = latest_complete_xnys_session(as_of_utc)
    errors: list[str] = []

    try:
        warnings = validate_ohlcv(data)
    except DataQualityError as error:
        return DataQualityReport(
            symbol=normalized_symbol,
            expected_latest_session=expected_latest,
            first_session=None,
            last_session=None,
            missing_sessions=(),
            errors=(str(error),),
            warnings=(),
        )

    tickers = set(data["ticker"].astype(str).str.strip().str.upper())
    if tickers != {normalized_symbol}:
        errors.append(
            f"symbol mismatch: expected {normalized_symbol}, got {sorted(tickers)}"
        )

    session_dates = tuple(pd.to_datetime(data["timestamp_utc"], utc=True).dt.date)
    first_session = session_dates[0]
    last_session = session_dates[-1]
    calendar = xcals.get_calendar("XNYS")
    comparison_end = max(last_session, expected_latest)
    valid_sessions = {
        session.date()
        for session in calendar.sessions_in_range(first_session, comparison_end)
    }
    non_sessions = tuple(sorted(set(session_dates).difference(valid_sessions)))
    if non_sessions:
        errors.append(
            "non-XNYS session dates: "
            + ", ".join(session.isoformat() for session in non_sessions)
        )

    expected_sessions = tuple(
        session.date()
        for session in calendar.sessions_in_range(first_session, expected_latest)
    )
    actual_sessions = set(session_dates)
    missing_sessions = tuple(
        session for session in expected_sessions if session not in actual_sessions
    )

    if last_session < expected_latest:
        errors.append(
            f"stale data: last session {last_session.isoformat()}, "
            f"expected {expected_latest.isoformat()}"
        )
    elif last_session > expected_latest:
        errors.append(
            f"data extends beyond latest complete XNYS session {expected_latest.isoformat()}"
        )

    return DataQualityReport(
        symbol=normalized_symbol,
        expected_latest_session=expected_latest,
        first_session=first_session,
        last_session=last_session,
        missing_sessions=missing_sessions,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )
