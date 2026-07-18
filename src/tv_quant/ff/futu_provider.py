"""Read-only Futu option snapshots behind an injected quote-context boundary."""

from __future__ import annotations

import random
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from math import isfinite
from numbers import Real
from typing import Any, Literal

from .math import normalize_iv
from .models import OptionLeg


_MAX_ATTEMPTS = 4
_BACKOFF_SECONDS = (0.5, 1.0, 2.0)
_SNAPSHOT_BATCH_SIZE = 400
_FUTU_TIMEOUT_MESSAGES = frozenset(
    {
        "PacketErr.Timeout",
        "Abnormal event timeout",
        "Connect timeout",
    }
)
_IV_SOURCE_FIELDS: tuple[tuple[str, Literal["percent", "decimal"]], ...] = (
    ("implied_volatility", "percent"),
    ("option_implied_volatility", "percent"),
)


@dataclass(frozen=True, slots=True, kw_only=True)
class FutuOptionRow(OptionLeg):
    """Option leg plus the unmodified IV value and its declared source unit."""

    raw_iv: float
    raw_iv_unit: Literal["percent", "decimal"]


@dataclass(slots=True)
class ProviderMetrics:
    """Per-provider request, retry, runtime, and quota-impact telemetry."""

    request_count: int = 0
    retry_count: int = 0
    snapshot_request_count: int = 0
    subscription_request_count: int = 0
    historical_quota_request_count: int = 0
    elapsed_seconds: float = 0.0
    method_counts: dict[str, int] = field(default_factory=dict)


class IncompleteOptionChainError(RuntimeError):
    """Raised when Futu returns incomplete or inconsistent contract identity."""


@dataclass(frozen=True, slots=True)
class _QuoteRuntime:
    context: object
    ret_ok: object
    ready_status: object


def _default_quote_context_factory() -> _QuoteRuntime:
    try:
        from futu import OpenQuoteContext, ProgramStatusType, RET_OK
    except ImportError as error:
        raise RuntimeError("Futu option source requires futu-api") from error
    return _QuoteRuntime(
        context=OpenQuoteContext(host="127.0.0.1", port=11111),
        ret_ok=RET_OK,
        ready_status=ProgramStatusType.READY,
    )


class FutuOptionProvider:
    """Fetch option data through quote-only snapshot APIs."""

    def __init__(
        self,
        *,
        quote_context_factory: Callable[[], object] = _default_quote_context_factory,
        ret_ok: object = 0,
        ready_status: object = "READY",
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._quote_context_factory = quote_context_factory
        self._ret_ok = ret_ok
        self._ready_status = ready_status
        self._sleep = sleep
        self._jitter = jitter if jitter is not None else lambda: random.uniform(0.0, 0.1)
        self._clock = clock
        self._context: object | None = None
        self.metrics = ProviderMetrics()

    def __enter__(self) -> FutuOptionProvider:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the owned quote context once without making another provider request."""
        context = self._context
        self._context = None
        if context is not None:
            _close_context(context)

    def get_expiries(self, ticker: str) -> list[date]:
        """Return the provider's available expiry dates in stable order."""
        payload = self._request("get_option_expiration_date", self._futu_code(ticker))
        expiries = {_as_date(row["strike_time"]) for row in _records(payload)}
        return sorted(expiries)

    def get_option_snapshot(self, ticker: str, expiry: date) -> list[FutuOptionRow]:
        """Return normalized option rows for one underlying and expiry."""
        ticker_name = self._ticker_name(ticker)
        expiry_text = expiry.isoformat()
        chain_payload = self._request(
            "get_option_chain",
            self._futu_code(ticker_name),
            start=expiry_text,
            end=expiry_text,
        )
        chain = _records(chain_payload)
        chain_entries = _validate_chain_identity(
            chain,
            expected_owner=self._futu_code(ticker_name),
            expected_expiry=expiry,
        )
        codes = [code for code, _ in chain_entries]
        if len(codes) != len(set(codes)):
            raise IncompleteOptionChainError(
                "Futu returned incomplete option chain: duplicate chain codes"
            )
        chain_by_code = dict(chain_entries)
        if not codes:
            return []

        snapshots: list[tuple[str, Mapping[str, Any]]] = []
        for start in range(0, len(codes), _SNAPSHOT_BATCH_SIZE):
            requested_codes = codes[start : start + _SNAPSHOT_BATCH_SIZE]
            payload = self._request(
                "get_market_snapshot",
                requested_codes,
                request_kind="snapshot",
            )
            returned_rows = _records(payload)
            snapshots.extend(_require_exact_snapshot_codes(requested_codes, returned_rows))

        rows: list[FutuOptionRow] = []
        for contract_symbol, snapshot in snapshots:
            chain_row = chain_by_code.get(contract_symbol)
            if chain_row is None:
                raise IncompleteOptionChainError(
                    "Futu returned incomplete option chain: snapshot identity mismatch"
                )
            raw_iv, raw_iv_unit = _extract_iv(snapshot)
            rows.append(
                FutuOptionRow(
                    ticker=ticker_name,
                    expiry=expiry,
                    option_type=_option_type(_pick(snapshot, chain_row, "option_type")),
                    strike=float(
                        _pick_known(snapshot, chain_row, "option_strike_price", "strike_price")
                    ),
                    bid=float(snapshot["bid_price"]),
                    ask=float(snapshot["ask_price"]),
                    iv=normalize_iv(raw_iv, raw_iv_unit),
                    delta=float(_pick_known(snapshot, chain_row, "option_delta", "delta")),
                    open_interest=int(
                        float(
                            _pick_known(
                                snapshot,
                                chain_row,
                                "option_open_interest",
                                "open_interest",
                            )
                        )
                    ),
                    volume=int(float(snapshot["volume"])),
                    contract_symbol=contract_symbol,
                    raw_iv=raw_iv,
                    raw_iv_unit=raw_iv_unit,
                )
            )
        return rows

    def get_underlying_option_volume(self, ticker: str) -> int:
        """Sum current option volume across every available expiry."""
        return sum(
            row.volume
            for expiry in self.get_expiries(ticker)
            for row in self.get_option_snapshot(ticker, expiry)
        )

    def _request(
        self,
        method_name: str,
        *args: object,
        request_kind: Literal["control", "snapshot"] = "control",
        **kwargs: object,
    ) -> object:
        context = self._ensure_context()
        return self._request_on_context(
            context,
            method_name,
            *args,
            request_kind=request_kind,
            **kwargs,
        )

    def _ensure_context(self) -> object:
        if self._context is not None:
            return self._context
        created = self._quote_context_factory()
        if isinstance(created, _QuoteRuntime):
            context = created.context
            self._ret_ok = created.ret_ok
            self._ready_status = created.ready_status
        else:
            context = created
        try:
            state = self._request_on_context(context, "get_global_state")
            qot_logined = state.get("qot_logined") if isinstance(state, Mapping) else None
            program_status = state.get("program_status_type") if isinstance(state, Mapping) else None
            if qot_logined is not True or program_status != self._ready_status:
                raise RuntimeError(
                    "Futu OpenD is unavailable: "
                    f"qot_logined={qot_logined!r}, program_status_type={program_status!r}"
                )
        except BaseException:
            try:
                _close_context(context)
            except BaseException:
                pass
            raise
        self._context = context
        return context

    def _request_on_context(
        self,
        context: object,
        method_name: str,
        *args: object,
        request_kind: Literal["control", "snapshot"] = "control",
        **kwargs: object,
    ) -> object:
        method = getattr(context, method_name)
        for attempt in range(_MAX_ATTEMPTS):
            self._record_request(method_name, request_kind)
            started = self._clock()
            try:
                result = method(*args, **kwargs)
            except TimeoutError:
                if attempt == _MAX_ATTEMPTS - 1:
                    raise
                self._schedule_retry(attempt)
                continue
            finally:
                self.metrics.elapsed_seconds += max(0.0, self._clock() - started)
            if not isinstance(result, tuple) or len(result) != 2:
                raise RuntimeError(f"Futu {method_name} returned an invalid response")
            ret, payload = result
            if ret != self._ret_ok:
                if _is_futu_timeout_payload(payload):
                    if attempt == _MAX_ATTEMPTS - 1:
                        raise TimeoutError(f"Futu {method_name} timed out: {payload}")
                    self._schedule_retry(attempt)
                    continue
                raise RuntimeError(f"Futu {method_name} failed: {payload}")
            return payload
        raise RuntimeError("unreachable retry state")

    def _schedule_retry(self, attempt: int) -> None:
        raw_jitter = self._jitter()
        if isinstance(raw_jitter, bool) or not isinstance(raw_jitter, Real):
            raise ValueError("retry jitter must be finite and non-negative")
        jitter = float(raw_jitter)
        if not isfinite(jitter) or jitter < 0:
            raise ValueError("retry jitter must be finite and non-negative")
        self.metrics.retry_count += 1
        self._sleep(_BACKOFF_SECONDS[attempt] + jitter)

    def _record_request(self, method_name: str, request_kind: str) -> None:
        self.metrics.request_count += 1
        self.metrics.method_counts[method_name] = self.metrics.method_counts.get(method_name, 0) + 1
        if request_kind == "snapshot":
            self.metrics.snapshot_request_count += 1

    @staticmethod
    def _ticker_name(ticker: str) -> str:
        value = ticker.strip().upper()
        if value.startswith("US."):
            value = value[3:]
        if not value:
            raise ValueError("ticker must not be empty")
        return value

    @classmethod
    def _futu_code(cls, ticker: str) -> str:
        return f"US.{cls._ticker_name(ticker)}"


def _records(payload: object) -> list[Mapping[str, Any]]:
    if hasattr(payload, "to_dict"):
        converted = payload.to_dict(orient="records")
        if isinstance(converted, list):
            return converted
    if isinstance(payload, Mapping):
        return [payload]
    if isinstance(payload, Iterable) and not isinstance(payload, (str, bytes)):
        rows = list(payload)
        if all(isinstance(row, Mapping) for row in rows):
            return rows
    raise RuntimeError("Futu returned unsupported tabular data")


def _require_exact_snapshot_codes(
    requested_codes: list[str], returned_rows: list[Mapping[str, Any]]
) -> list[tuple[str, Mapping[str, Any]]]:
    validated_rows = [
        (_require_contract_code(row.get("code"), "snapshot"), row)
        for row in returned_rows
    ]
    returned_codes = [code for code, _ in validated_rows]
    if Counter(returned_codes) != Counter(requested_codes):
        raise IncompleteOptionChainError(
            "Futu returned incomplete option chain: snapshot identity mismatch"
        )
    return validated_rows


def _validate_chain_identity(
    chain: list[Mapping[str, Any]],
    *,
    expected_owner: str,
    expected_expiry: date,
) -> list[tuple[str, Mapping[str, Any]]]:
    validated: list[tuple[str, Mapping[str, Any]]] = []
    for row in chain:
        code = _require_contract_code(row.get("code"), "chain")
        owner = row.get("stock_owner")
        if not isinstance(owner, str) or owner != expected_owner:
            raise IncompleteOptionChainError(
                "Futu returned incomplete option chain: chain owner identity mismatch"
            )
        strike_time = row.get("strike_time")
        if not isinstance(strike_time, str):
            raise IncompleteOptionChainError(
                "Futu returned incomplete option chain: chain expiry identity mismatch"
            )
        try:
            parsed_expiry = date.fromisoformat(strike_time)
        except ValueError as error:
            raise IncompleteOptionChainError(
                "Futu returned incomplete option chain: chain expiry identity mismatch"
            ) from error
        if parsed_expiry != expected_expiry:
            raise IncompleteOptionChainError(
                "Futu returned incomplete option chain: chain expiry identity mismatch"
            )
        validated.append((code, row))
    return validated


def _require_contract_code(value: object, source: Literal["chain", "snapshot"]) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise IncompleteOptionChainError(
            f"Futu returned incomplete option chain: invalid {source} code"
        )
    return value


def _is_futu_timeout_payload(payload: object) -> bool:
    return isinstance(payload, str) and payload in _FUTU_TIMEOUT_MESSAGES


def _close_context(context: object) -> None:
    close = getattr(context, "close", None)
    if callable(close):
        close()


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _extract_iv(snapshot: Mapping[str, Any]) -> tuple[float, Literal["percent", "decimal"]]:
    for field_name, unit in _IV_SOURCE_FIELDS:
        if field_name in snapshot:
            return float(snapshot[field_name]), unit
    raise ValueError("Futu snapshot has no recognized IV field with a declared unit")


def _pick(primary: Mapping[str, Any], fallback: Mapping[str, Any], key: str) -> object:
    return primary[key] if key in primary else fallback[key]


def _pick_known(
    primary: Mapping[str, Any], fallback: Mapping[str, Any], *keys: str
) -> object:
    for row in (primary, fallback):
        for key in keys:
            if key in row:
                return row[key]
    raise KeyError(keys[0])


def _option_type(value: object) -> str:
    if hasattr(value, "value"):
        value = value.value
    return str(value).rsplit(".", maxsplit=1)[-1].upper()
