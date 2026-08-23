"""Raw, quota-safe Futu endpoint acquisition for the Universe Foundation.

This module deliberately preserves provider facts without interpreting them.
Qualification, identity, freshness, and membership all belong to later stages.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import isfinite
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
    MARKET_STATE_POLICY = RatePolicy(
        max_items=400,
        max_requests=10,
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
        self._market_state_limiter = _SlidingWindowLimiter(
            self.MARKET_STATE_POLICY, clock, sleep
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

    def market_states(self, codes: Sequence[str]) -> tuple[RawApiBatch, ...]:
        """Acquire raw per-security market state without interpreting its enum."""
        chunks = self._chunks(codes, self.MARKET_STATE_POLICY.max_items)
        if not chunks:
            return ()
        context = self._open_context()
        try:
            batches: list[RawApiBatch] = []
            for batch_index, chunk in enumerate(chunks, start=1):
                request = {"codes": list(chunk)}
                result = self._request(
                    endpoint="market_states",
                    context=context,
                    invoke=lambda chunk=chunk: context.get_market_state(list(chunk)),
                    limiter=self._market_state_limiter,
                )
                batches.append(
                    self._batch(
                        endpoint="market_states",
                        batch_index=batch_index,
                        request=request,
                        result=result,
                    )
                )
            return tuple(batches)
        finally:
            context.close()

    def collect_runtime_evidence(
        self,
        *,
        notification_window_seconds: float,
    ) -> tuple[RawApiBatch, ...]:
        """Capture raw SDK, OpenD, and QOT_RIGHT observations in one context."""
        if isinstance(notification_window_seconds, bool) or not isinstance(
            notification_window_seconds, (int, float)
        ):
            raise ValueError("notification_window_seconds must be a nonnegative number")

        window = float(notification_window_seconds)
        if not isfinite(window) or window < 0:
            raise ValueError("notification_window_seconds must be a nonnegative finite number")
        sdk_version = getattr(self._sdk, "__version__", None)
        if not isinstance(sdk_version, str) or not sdk_version:
            raise FutuProviderError("Futu runtime SDK version is unavailable")

        events: list[Mapping[str, Any]] = []
        context = self._open_context()
        try:
            handler_result = context.set_handler(self._qot_right_handler(events))
            if handler_result != self._ret_ok():
                raise FutuProviderError("Futu QOT_RIGHT handler registration failed")
            runtime_batch = self._batch(
                endpoint="runtime_sdk_version",
                batch_index=1,
                request={},
                result=(self._ret_ok(), {"sdk_version": sdk_version}),
            )
            global_state = self._request(
                endpoint="global_state",
                context=context,
                invoke=context.get_global_state,
            )
            global_batch = self._batch(
                endpoint="global_state",
                batch_index=1,
                request={},
                result=global_state,
            )
            self._sleep(window)
            qot_right_batch = self._batch(
                endpoint="qot_right_capture",
                batch_index=1,
                request={"notification_window_seconds": window},
                result=(self._ret_ok(), {"events": events}),
            )
            return runtime_batch, global_batch, qot_right_batch
        finally:
            context.close()

    def probe_realtime_quote_capability(self, code: str) -> RawApiBatch:
        """Capture one scope-limited QUOTE capability and cleanup lifecycle."""
        if type(code) is not str or not code.strip():
            raise ValueError("code must be a non-empty string")
        sdk_version = getattr(self._sdk, "__version__", None)
        subtype = getattr(getattr(self._sdk, "SubType", None), "QUOTE", None)
        if not isinstance(sdk_version, str) or not sdk_version:
            raise FutuProviderError("Futu runtime SDK version is unavailable")
        if subtype is None:
            raise FutuProviderError("Futu runtime does not expose SubType.QUOTE")

        def raw_record(endpoint: str, operation_request: Mapping[str, Any], result: object) -> Mapping[str, Any]:
            canonical_request = _canonical_raw(operation_request)
            if not isinstance(result, tuple) or len(result) < 2:
                response: Any = {"error": repr(result)}
                return {
                    "request": canonical_request,
                    "ret": None,
                    "response": response,
                    "request_hash": _raw_hash(endpoint, "request", canonical_request),
                    "response_hash": _raw_hash(endpoint, "response", response),
                }
            record: dict[str, Any] = {
                "request": canonical_request,
                "ret": _canonical_raw(result[0]),
                "response": _canonical_raw(result[1]),
            }
            if len(result) > 2:
                record["extra"] = _canonical_raw(result[2:])
            record["request_hash"] = _raw_hash(endpoint, "request", canonical_request)
            record["response_hash"] = _raw_hash(endpoint, "response", {
                key: value for key, value in record.items() if key not in {"request_hash", "response_hash"}
            })
            return record

        def successful_payload(result: object) -> Mapping[str, Any]:
            if not isinstance(result, tuple) or len(result) < 2 or result[0] != self._ret_ok():
                return {}
            payload = _canonical_raw(result[1])
            return payload if isinstance(payload, Mapping) else {"data": payload}

        def remaining_quota(record: Mapping[str, Any]) -> int | float | None:
            response = record.get("response")
            if not isinstance(response, Mapping):
                return None
            value = response.get("remain")
            return value if type(value) in {int, float} else None

        def contains_code(value: object, target: str) -> bool:
            if isinstance(value, Mapping):
                return any(contains_code(item, target) for item in value.values())
            if isinstance(value, (tuple, list)):
                return any(contains_code(item, target) for item in value)
            return value == target

        request = {"code": code.strip(), "subtype": "QUOTE", "subscribe_push": False}
        context = self._open_context()
        started_at = _utc(self._clock())
        close_attempted = False
        try:
            global_result = context.get_global_state()
            global_payload = successful_payload(global_result)
            opend_version = global_payload.get("server_ver")
            if not isinstance(opend_version, str) or not opend_version:
                opend_version = "UNKNOWN"

            try:
                subscribe_result: object = context.subscribe(
                    code_list=[code.strip()],
                    subtype_list=[subtype],
                    subscribe_push=False,
                )
            except Exception as error:
                subscribe_result = (None, {"error": repr(error)})
            subscribed_at = _utc(self._clock())
            subscribe_ok = (
                isinstance(subscribe_result, tuple)
                and len(subscribe_result) >= 2
                and subscribe_result[0] == self._ret_ok()
            )

            query_after_subscribe: Mapping[str, Any] = {}
            query_after_unsubscribe: Mapping[str, Any] = {}
            unsubscribe_record: Mapping[str, Any] = {}
            capability_verdict = "PROVEN_SCOPE_LIMITED" if subscribe_ok else "UNKNOWN"
            cleanup_verdict = "UNKNOWN"
            if subscribe_ok:
                try:
                    query_result = context.query_subscription()
                    query_after_subscribe = raw_record("query_subscription_after_subscribe", {}, query_result)
                except Exception as error:
                    query_after_subscribe = raw_record(
                        "query_subscription_after_subscribe", {}, (None, {"error": repr(error)})
                    )
                self._sleep(60.0)
                try:
                    unsubscribe_result: object = context.unsubscribe(
                        code_list=[code.strip()],
                        subtype_list=[subtype],
                    )
                except Exception as error:
                    unsubscribe_result = (None, {"error": repr(error)})
                unsubscribe_record = raw_record(
                    "unsubscribe", {"code_list": [code.strip()], "subtype_list": ["QUOTE"]}, unsubscribe_result
                )
                unsubscribe_ok = (
                    isinstance(unsubscribe_result, tuple)
                    and len(unsubscribe_result) >= 2
                    and unsubscribe_result[0] == self._ret_ok()
                )
                query_after_unsubscribe_ok = False
                try:
                    query_after_unsubscribe_result = context.query_subscription()
                    query_after_unsubscribe = raw_record(
                        "query_subscription_after_unsubscribe", {}, query_after_unsubscribe_result
                    )
                    query_after_unsubscribe_ok = (
                        isinstance(query_after_unsubscribe_result, tuple)
                        and len(query_after_unsubscribe_result) >= 2
                        and query_after_unsubscribe_result[0] == self._ret_ok()
                    )
                except Exception as error:
                    query_after_unsubscribe = raw_record(
                        "query_subscription_after_unsubscribe", {}, (None, {"error": repr(error)})
                    )

                held_seconds = int(max((_utc(self._clock()) - subscribed_at).total_seconds(), 0.0))
                pre_remaining = remaining_quota(query_after_subscribe)
                post_remaining = remaining_quota(query_after_unsubscribe)
                post_response = query_after_unsubscribe.get("response")
                target_absent = not contains_code(post_response, code.strip())
                quota_restored = (
                    pre_remaining is not None
                    and post_remaining is not None
                    and post_remaining > pre_remaining
                )
                if held_seconds < 60.0:
                    cleanup_verdict = "DELAYED_RELEASE_RISK"
                elif unsubscribe_ok and query_after_unsubscribe_ok and target_absent and quota_restored:
                    cleanup_verdict = "UNSUBSCRIBE_CONFIRMED"
                else:
                    cleanup_verdict = "CLEANUP_FAILED"
            else:
                held_seconds = int(max((_utc(self._clock()) - subscribed_at).total_seconds(), 0.0))

            close_attempted = True
            try:
                close_result = context.close()
                close_response: Mapping[str, Any] = {"attempted": True, "succeeded": True, "result": _canonical_raw(close_result)}
            except Exception as error:
                close_response = {"attempted": True, "succeeded": False, "error": repr(error)}
                if cleanup_verdict == "UNSUBSCRIBE_CONFIRMED":
                    cleanup_verdict = "CLEANUP_FAILED"
            close_record = dict(close_response)
            close_record["response_hash"] = _raw_hash("close", "response", close_response)

            response = {
                "provider_sdk_version": sdk_version,
                "opend_server_version": opend_version,
                "started_at_utc": started_at.isoformat(),
                "subscribed_at_utc": subscribed_at.isoformat(),
                "cleanup_at_utc": _utc(self._clock()).isoformat(),
                "held_seconds": held_seconds,
                "subscribe": raw_record("subscribe", request, subscribe_result),
                "query_after_subscribe": query_after_subscribe,
                "unsubscribe": unsubscribe_record,
                "query_after_unsubscribe": query_after_unsubscribe,
                "close": close_record,
                "capability_verdict": capability_verdict,
                "cleanup_verdict": cleanup_verdict,
            }
            return self._batch(
                endpoint="realtime_quote_capability_probe",
                batch_index=1,
                request=request,
                result=(self._ret_ok(), response),
            )
        finally:
            if not close_attempted:
                context.close()

    def _qot_right_handler(self, events: list[Mapping[str, Any]]) -> Any:
        handler_base = getattr(self._sdk, "SysNotifyHandlerBase", None)
        notify_types = getattr(self._sdk, "SysNotifyType", None)
        qot_right_type = getattr(notify_types, "QOT_RIGHT", None)
        if not isinstance(handler_base, type) or qot_right_type is None:
            raise FutuProviderError("Futu runtime does not expose QOT_RIGHT notifications")
        adapter = self

        class QotRightHandler(handler_base):
            def on_recv_rsp(self, response: Any) -> Any:
                result = super().on_recv_rsp(response)
                if not isinstance(result, tuple) or len(result) != 2:
                    return result
                ret_code, data = result
                if ret_code != adapter._ret_ok():
                    return result
                if not isinstance(data, tuple) or len(data) != 3:
                    return result
                notify_type, sub_type, message = data
                if notify_type == qot_right_type:
                    events.append(
                        {
                            "notify_type": notify_type,
                            "sub_type": sub_type,
                            "msg": message,
                        }
                    )
                return result

        return QotRightHandler()

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
