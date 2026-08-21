"""Raw, quota-safe Futu endpoint acquisition for the Universe Foundation.

This module deliberately preserves provider facts without interpreting them.
Qualification, identity, freshness, and membership all belong to later stages.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any

from tv_quant.run_manifest import canonical_hash


class FutuProviderError(RuntimeError):
    """An explicit raw-acquisition failure returned by the provider."""


@dataclass(frozen=True, slots=True)
class RatePolicy:
    max_items: int
    max_requests: int
    window_seconds: float

    def __post_init__(self) -> None:
        if self.max_items < 1 or self.max_requests < 1 or self.window_seconds <= 0:
            raise ValueError("rate policy values must be positive")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("clock must return an aware UTC datetime")
    return value.astimezone(UTC)


def _canonical_raw(value: Any) -> Any:
    """Represent arbitrary SDK values canonically without replacing nulls."""
    if value is None or type(value) in {bool, int, str}:
        return value
    if isinstance(value, Mapping):
        return {str(key): _canonical_raw(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical_raw(item) for item in value]
    if isinstance(value, datetime):
        return {"__datetime__": _utc(value).isoformat()}
    if isinstance(value, bytes):
        return {"__bytes_hex__": value.hex()}
    if type(value) is float:
        return {"__float_repr__": repr(value)}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return {"__table_records__": _canonical_raw(to_dict(orient="records"))}
        except TypeError:
            return {"__table_records__": _canonical_raw(to_dict())}
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int)):
        return {"__enum_value__": enum_value}
    return {"__repr__": repr(value)}


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _raw_hash(endpoint: str, field: str, value: Any) -> str:
    return canonical_hash({"endpoint": endpoint, field: value})


@dataclass(frozen=True, slots=True)
class RawApiBatch:
    endpoint: str
    batch_index: int
    raw_request: Mapping[str, Any]
    raw_response: Mapping[str, Any]
    request_hash: str
    response_hash: str
    ret_code: Any
    acquisition_status: str
    acquired_at_utc: datetime

    def __post_init__(self) -> None:
        if self.batch_index < 1:
            raise ValueError("batch_index must be positive")
        if self.acquisition_status != "SUCCESS":
            raise ValueError("raw batches only represent successful acquisition")
        object.__setattr__(self, "raw_request", _freeze(_canonical_raw(self.raw_request)))
        object.__setattr__(self, "raw_response", _freeze(_canonical_raw(self.raw_response)))
        object.__setattr__(self, "acquired_at_utc", _utc(self.acquired_at_utc))


@dataclass(frozen=True, slots=True)
class RawApiPage:
    endpoint: str
    page_index: int
    continuation: Mapping[str, Any]
    is_last_page: bool
    raw_request: Mapping[str, Any]
    raw_response: Mapping[str, Any]
    request_hash: str
    response_hash: str
    ret_code: Any
    acquisition_status: str
    acquired_at_utc: datetime

    def __post_init__(self) -> None:
        if self.page_index < 1:
            raise ValueError("page_index must be positive")
        if type(self.is_last_page) is not bool:
            raise ValueError("is_last_page must be bool")
        if self.acquisition_status != "SUCCESS":
            raise ValueError("raw pages only represent successful acquisition")
        object.__setattr__(self, "continuation", _freeze(_canonical_raw(self.continuation)))
        object.__setattr__(self, "raw_request", _freeze(_canonical_raw(self.raw_request)))
        object.__setattr__(self, "raw_response", _freeze(_canonical_raw(self.raw_response)))
        object.__setattr__(self, "acquired_at_utc", _utc(self.acquired_at_utc))


@dataclass(slots=True)
class _SlidingWindowLimiter:
    policy: RatePolicy
    clock: Callable[[], datetime]
    sleep: Callable[[float], None]
    _timestamps: list[datetime] = field(default_factory=list)

    def acquire(self) -> None:
        while True:
            now = _utc(self.clock())
            cutoff = now - timedelta(seconds=self.policy.window_seconds)
            self._timestamps = [stamp for stamp in self._timestamps if stamp > cutoff]
            if len(self._timestamps) < self.policy.max_requests:
                self._timestamps.append(now)
                return
            wait_until = self._timestamps[0] + timedelta(seconds=self.policy.window_seconds)
            delay = (wait_until - now).total_seconds()
            self.sleep(max(delay, 0.0))


class FutuProviderAdapter:
    """Futu/OpenD raw endpoint adapter with bounded retry and independent limits."""

    MARKET_SNAPSHOT_POLICY = RatePolicy(
        max_items=400,
        max_requests=60,
        window_seconds=30.0,
    )
    OWNER_PLATE_POLICY = RatePolicy(
        max_items=200,
        max_requests=10,
        window_seconds=30.0,
    )
    SCREEN_POLICY = RatePolicy(
        max_items=200,
        max_requests=10,
        window_seconds=30.0,
    )
    SCREEN_PAGE_SIZE = 200
    MAX_SCREEN_PAGES = 1_000
    MAX_ATTEMPTS = 3
    RETRY_BACKOFF_SECONDS = 1.0

    def __init__(
        self,
        *,
        sdk: Any,
        clock: Callable[[], datetime],
        sleep: Callable[[float], None],
    ) -> None:
        self._sdk = sdk
        self._clock = clock
        self._sleep = sleep
        self._market_limiter = _SlidingWindowLimiter(
            self.MARKET_SNAPSHOT_POLICY, clock, sleep
        )
        self._owner_limiter = _SlidingWindowLimiter(
            self.OWNER_PLATE_POLICY, clock, sleep
        )
        self._screen_limiter = _SlidingWindowLimiter(self.SCREEN_POLICY, clock, sleep)

    def _open_context(self) -> Any:
        return self._sdk.OpenQuoteContext()

    def _ret_ok(self) -> Any:
        return self._sdk.RET_OK

    @staticmethod
    def _retryable(detail: object) -> bool:
        text = str(detail).lower()
        return any(token in text for token in ("temporary", "timeout", "network", "rate", "busy"))

    def _request(
        self,
        *,
        endpoint: str,
        context: Any,
        invoke: Callable[[], Any],
        limiter: _SlidingWindowLimiter | None = None,
    ) -> tuple[Any, ...]:
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            if limiter is not None:
                limiter.acquire()
            try:
                result = invoke()
            except Exception as error:
                if self._retryable(error) and attempt < self.MAX_ATTEMPTS:
                    self._sleep(self.RETRY_BACKOFF_SECONDS)
                    continue
                raise
            if not isinstance(result, tuple) or len(result) < 2:
                raise FutuProviderError(
                    f"Futu acquisition failed endpoint={endpoint}: invalid SDK return"
                )
            ret_code, detail = result[0], result[1]
            if ret_code == self._ret_ok():
                return result
            if self._retryable(detail) and attempt < self.MAX_ATTEMPTS:
                self._sleep(self.RETRY_BACKOFF_SECONDS)
                continue
            if self._retryable(detail):
                raise FutuProviderError(
                    "FUTU_RATE_LIMIT_RETRY_EXHAUSTED: "
                    f"endpoint={endpoint} ret_code={ret_code!r} detail={detail!r}"
                )
            raise FutuProviderError(
                f"Futu acquisition failed endpoint={endpoint} ret_code={ret_code!r} detail={detail!r}"
            )
        raise AssertionError("bounded retry loop must return or raise")

    def _batch(
        self,
        *,
        endpoint: str,
        batch_index: int,
        request: Mapping[str, Any],
        result: tuple[Any, ...],
    ) -> RawApiBatch:
        if isinstance(result[1], Mapping) and len(result) == 2:
            response: Mapping[str, Any] = result[1]
        else:
            response = {"data": result[1], "extra": list(result[2:])}
        canonical_request = _canonical_raw(request)
        canonical_response = _canonical_raw(response)
        return RawApiBatch(
            endpoint=endpoint,
            batch_index=batch_index,
            raw_request=canonical_request,
            raw_response=canonical_response,
            request_hash=_raw_hash(endpoint, "request", canonical_request),
            response_hash=_raw_hash(endpoint, "response", canonical_response),
            ret_code=result[0],
            acquisition_status="SUCCESS",
            acquired_at_utc=_utc(self._clock()),
        )

    def discover_cash_securities(self) -> tuple[RawApiBatch, ...]:
        security_types = self._sdk.SecurityType
        categories = tuple(
            getattr(security_types, name)
            for name in ("STOCK", "ETF", "WARRANT", "BWRT", "BOND")
        )
        context = self._open_context()
        try:
            batches: list[RawApiBatch] = []
            for batch_index, category in enumerate(categories, start=1):
                request = {"market": self._sdk.Market.US, "stock_type": category}
                result = self._request(
                    endpoint="discover_cash_securities",
                    context=context,
                    invoke=lambda request=request: context.get_stock_basicinfo(**request),
                )
                batches.append(
                    self._batch(
                        endpoint="discover_cash_securities",
                        batch_index=batch_index,
                        request=request,
                        result=result,
                    )
                )
            return tuple(batches)
        finally:
            context.close()

    def screen_all_pages(self) -> tuple[RawApiPage, ...]:
        context = self._open_context()
        try:
            pages: list[RawApiPage] = []
            page_from = 0
            for page_index in range(1, self.MAX_SCREEN_PAGES + 1):
                screen_request = self._screen_request(page_from)
                request = self._screen_request_record(page_from)
                result = self._request(
                    endpoint="screen_all_pages",
                    context=context,
                    invoke=lambda: context.get_stock_screen(screen_request),
                    limiter=self._screen_limiter,
                )
                if len(result) != 2 or not isinstance(result[1], tuple) or len(result[1]) != 3:
                    raise FutuProviderError(
                        "FUTU_PAGINATION_BLOCKER: screen response must include last_page"
                    )
                last_page, all_count, rows = result[1]
                if type(last_page) is not bool:
                    raise FutuProviderError(
                        "FUTU_PAGINATION_BLOCKER: last_page must be bool"
                    )
                try:
                    row_count = len(rows)
                except TypeError as error:
                    raise FutuProviderError(
                        "FUTU_PAGINATION_BLOCKER: screen rows must be sized"
                    ) from error
                continuation = {"page_from": page_from, "last_page": last_page}
                response = {
                    "last_page": last_page,
                    "all_count": all_count,
                    "rows": rows,
                }
                canonical_request = _canonical_raw(request)
                canonical_response = _canonical_raw(response)
                pages.append(
                    RawApiPage(
                        endpoint="screen_all_pages",
                        page_index=page_index,
                        continuation=continuation,
                        is_last_page=last_page,
                        raw_request=canonical_request,
                        raw_response=canonical_response,
                        request_hash=_raw_hash("screen_all_pages", "request", canonical_request),
                        response_hash=_raw_hash("screen_all_pages", "response", canonical_response),
                        ret_code=result[0],
                        acquisition_status="SUCCESS",
                        acquired_at_utc=_utc(self._clock()),
                    )
                )
                if last_page:
                    return tuple(pages)
                if row_count < 1:
                    raise FutuProviderError(
                        "FUTU_PAGINATION_BLOCKER: non-terminal screen page is empty"
                    )
                page_from += row_count
            raise FutuProviderError(
                "FUTU_PAGINATION_BLOCKER: maximum screen page count exceeded"
            )
        finally:
            context.close()

    def _screen_request(self, page_from: int) -> Any:
        request = self._sdk.StockScreenRequest()
        request.page_from = page_from
        request.page_count = self.SCREEN_PAGE_SIZE
        request.add_simple_field(
            field=self._sdk.SimpleField.MARKET,
            values=[self._sdk.ScrMarket.US],
        )
        for field in ("CODE", "NAME", "INDUSTRY"):
            request.add_retrieve_basic(name=getattr(self._sdk.BasicProperty, field))
        for field in ("PRICE", "MARKET_CAP", "LISTED_DAYS"):
            request.add_retrieve_simple(name=getattr(self._sdk.SimpleProperty, field))
        for field in ("AVG_TURNOVER", "AVG_VOLUME"):
            request.add_retrieve_cumulative(
                name=getattr(self._sdk.CumulativeProperty, field), days=20
            )
        return request

    def _screen_request_record(self, page_from: int) -> Mapping[str, Any]:
        return {
            "market": self._sdk.ScrMarket.US,
            "page_from": page_from,
            "page_count": self.SCREEN_PAGE_SIZE,
            "retrieve_fields": [
                ("basic", self._sdk.BasicProperty.CODE, None),
                ("basic", self._sdk.BasicProperty.NAME, None),
                ("basic", self._sdk.BasicProperty.INDUSTRY, None),
                ("simple", self._sdk.SimpleProperty.PRICE, None),
                ("simple", self._sdk.SimpleProperty.MARKET_CAP, None),
                ("simple", self._sdk.SimpleProperty.LISTED_DAYS, None),
                ("cumulative", self._sdk.CumulativeProperty.AVG_TURNOVER, 20),
                ("cumulative", self._sdk.CumulativeProperty.AVG_VOLUME, 20),
            ],
        }

    @staticmethod
    def _chunks(codes: Sequence[str], size: int) -> tuple[tuple[str, ...], ...]:
        normalized = tuple(codes)
        return tuple(
            normalized[index : index + size]
            for index in range(0, len(normalized), size)
        )

    def market_snapshots(self, codes: Sequence[str]) -> tuple[RawApiBatch, ...]:
        chunks = self._chunks(codes, self.MARKET_SNAPSHOT_POLICY.max_items)
        if not chunks:
            return ()
        context = self._open_context()
        try:
            batches: list[RawApiBatch] = []
            for batch_index, chunk in enumerate(chunks, start=1):
                request = {"codes": list(chunk)}
                result = self._request(
                    endpoint="market_snapshots",
                    context=context,
                    invoke=lambda chunk=chunk: context.get_market_snapshot(list(chunk)),
                    limiter=self._market_limiter,
                )
                batches.append(
                    self._batch(
                        endpoint="market_snapshots",
                        batch_index=batch_index,
                        request=request,
                        result=result,
                    )
                )
            return tuple(batches)
        finally:
            context.close()

    def owner_plates(self, codes: Sequence[str]) -> tuple[RawApiBatch, ...]:
        chunks = self._chunks(codes, self.OWNER_PLATE_POLICY.max_items)
        if not chunks:
            return ()
        context = self._open_context()
        try:
            batches: list[RawApiBatch] = []
            for batch_index, chunk in enumerate(chunks, start=1):
                request = {"codes": list(chunk)}
                result = self._request(
                    endpoint="owner_plates",
                    context=context,
                    invoke=lambda chunk=chunk: context.get_owner_plate(list(chunk)),
                    limiter=self._owner_limiter,
                )
                batches.append(
                    self._batch(
                        endpoint="owner_plates",
                        batch_index=batch_index,
                        request=request,
                        result=result,
                    )
                )
            return tuple(batches)
        finally:
            context.close()
