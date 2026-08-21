from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tv_quant.pattern_finder.universe_foundation.futu_adapter import (
    FutuProviderAdapter,
    FutuProviderError,
    RawApiBatch,
    RawApiPage,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 21, tzinfo=UTC)
        self.sleeps: list[float] = []

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)


class FakeContext:
    def __init__(self, sdk: "FakeSdk") -> None:
        self.sdk = sdk
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def get_stock_basicinfo(self, **request: object):
        self.sdk.discovery_requests.append(request)
        return self.sdk.next_result("discovery")

    def get_stock_screen(self, request: object):
        self.sdk.screen_requests.append(
            {
                "page_from": request.page_from,
                "page_count": request.page_count,
                "queries": tuple(request.queries),
                "retrieves": tuple(request.retrieves),
            }
        )
        return self.sdk.next_result("screen")

    def get_market_snapshot(self, codes: list[str]):
        self.sdk.snapshot_requests.append(tuple(codes))
        return self.sdk.next_result("snapshot")

    def get_market_state(self, codes: list[str]):
        self.sdk.market_state_requests.append(tuple(codes))
        return self.sdk.next_result("market_state")

    def get_owner_plate(self, codes: list[str]):
        self.sdk.plate_requests.append(tuple(codes))
        return self.sdk.next_result("plate")

    def get_global_state(self):
        self.sdk.global_state_requests += 1
        return self.sdk.next_result("global_state")

    def set_handler(self, handler: object) -> None:
        self.sdk.handlers.append(handler)
        for notification in self.sdk.notifications.pop(0) if self.sdk.notifications else ():
            handler.on_recv_rsp(notification)  # type: ignore[attr-defined]
        return self.sdk.handler_result


class FakeSdk:
    RET_OK = 0
    __version__ = "10.09.6908"

    class SysNotifyType:
        QOT_RIGHT = "QOT_RIGHT"

    class SysNotifyHandlerBase:
        def on_recv_rsp(self, notification: object):
            return 0, notification

    class Market:
        US = "US"

    class SecurityType:
        STOCK = "STOCK"
        ETF = "ETF"
        WARRANT = "WARRANT"
        BWRT = "BWRT"
        BOND = "BOND"

    class ScrMarket:
        US = "US"

    class SimpleField:
        MARKET = "MARKET"

    class BasicProperty:
        CODE = "CODE"
        NAME = "NAME"
        INDUSTRY = "INDUSTRY"

    class SimpleProperty:
        PRICE = "PRICE"
        MARKET_CAP = "MARKET_CAP"
        LISTED_DAYS = "LISTED_DAYS"

    class CumulativeProperty:
        AVG_TURNOVER = "AVG_TURNOVER"
        AVG_VOLUME = "AVG_VOLUME"

    class StockScreenRequest:
        def __init__(self) -> None:
            self.page_from = 0
            self.page_count = 200
            self.queries: list[tuple[object, object]] = []
            self.retrieves: list[tuple[object, ...]] = []

        def add_simple_field(self, *, field: object, values: list[object]) -> None:
            self.queries.append((field, tuple(values)))

        def add_retrieve_basic(self, *, name: object) -> None:
            self.retrieves.append(("basic", name))

        def add_retrieve_simple(self, *, name: object) -> None:
            self.retrieves.append(("simple", name))

        def add_retrieve_cumulative(self, *, name: object, days: int) -> None:
            self.retrieves.append(("cumulative", name, days))

    def __init__(self) -> None:
        self.contexts: list[FakeContext] = []
        self.discovery_requests: list[dict[str, object]] = []
        self.screen_requests: list[dict[str, object]] = []
        self.snapshot_requests: list[tuple[str, ...]] = []
        self.market_state_requests: list[tuple[str, ...]] = []
        self.plate_requests: list[tuple[str, ...]] = []
        self.global_state_requests = 0
        self.handlers: list[object] = []
        self.notifications: list[list[object]] = []
        self.handler_result = 0
        self.results: dict[str, list[object]] = {
            "discovery": [],
            "screen": [],
            "snapshot": [],
            "market_state": [],
            "plate": [],
            "global_state": [],
        }

    def OpenQuoteContext(self) -> FakeContext:
        context = FakeContext(self)
        self.contexts.append(context)
        return context

    def next_result(self, endpoint: str):
        result = self.results[endpoint].pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _adapter(sdk: FakeSdk, clock: FakeClock | None = None) -> FutuProviderAdapter:
    fake_clock = clock or FakeClock()
    return FutuProviderAdapter(
        sdk=sdk,
        clock=fake_clock,
        sleep=fake_clock.sleep,
    )


def _ok(payload: object = None) -> tuple[int, object]:
    return 0, {} if payload is None else payload


def test_discovery_keeps_categories_and_raw_nulls_with_audit_hashes() -> None:
    sdk = FakeSdk()
    sdk.results["discovery"] = [
        _ok({"rows": [{"code": "US.AAA", "stock_type": "STOCK", "delisting": None}]})
        for _ in range(5)
    ]

    batches = _adapter(sdk).discover_cash_securities()

    assert len(batches) == 5
    assert all(isinstance(batch, RawApiBatch) for batch in batches)
    assert [request["stock_type"] for request in sdk.discovery_requests] == [
        "STOCK",
        "ETF",
        "WARRANT",
        "BWRT",
        "BOND",
    ]
    assert batches[0].raw_response["rows"][0]["delisting"] is None
    assert batches[0].request_hash != batches[1].request_hash
    assert len(batches[0].response_hash) == 64
    assert all(context.closed for context in sdk.contexts)


def test_screen_reads_each_page_in_order_until_provider_last_page() -> None:
    sdk = FakeSdk()
    sdk.results["screen"] = [
        (0, (False, 3, [{"code": "US.AAA"}, {"code": "US.BBB"}])),
        (0, (False, 3, [{"code": "US.CCC"}])),
        (0, (True, 3, [])),
    ]

    pages = _adapter(sdk).screen_all_pages()

    assert all(isinstance(page, RawApiPage) for page in pages)
    assert [page.page_index for page in pages] == [1, 2, 3]
    assert [tuple(page.raw_response["rows"]) for page in pages] == [
        ({"code": "US.AAA"}, {"code": "US.BBB"}),
        ({"code": "US.CCC"},),
        (),
    ]
    assert [request["page_from"] for request in sdk.screen_requests] == [0, 2, 3]
    assert pages[0].raw_request["market"] == "US"
    assert pages[0].raw_request["retrieve_fields"] == (
        ("basic", "CODE", None),
        ("basic", "NAME", None),
        ("basic", "INDUSTRY", None),
        ("simple", "PRICE", None),
        ("simple", "MARKET_CAP", None),
        ("simple", "LISTED_DAYS", None),
        ("cumulative", "AVG_TURNOVER", 20),
        ("cumulative", "AVG_VOLUME", 20),
    )
    assert pages[-1].is_last_page is True
    assert all(context.closed for context in sdk.contexts)


def test_hashes_are_deterministic_and_change_for_distinct_raw_responses() -> None:
    first_sdk = FakeSdk()
    first_sdk.results["snapshot"] = [_ok({"rows": [{"code": "US.AAA", "last_price": None}]})]
    second_sdk = FakeSdk()
    second_sdk.results["snapshot"] = [_ok({"rows": [{"code": "US.AAA", "last_price": None}]})]
    changed_sdk = FakeSdk()
    changed_sdk.results["snapshot"] = [_ok({"rows": [{"code": "US.AAA", "last_price": "101"}]})]

    first = _adapter(first_sdk).market_snapshots(["US.AAA"])[0]
    second = _adapter(second_sdk).market_snapshots(["US.AAA"])[0]
    changed = _adapter(changed_sdk).market_snapshots(["US.AAA"])[0]

    assert first.request_hash == second.request_hash
    assert first.response_hash == second.response_hash
    assert first.response_hash != changed.response_hash
    assert first.raw_response["rows"][0]["last_price"] is None


def test_provider_ret_code_is_an_explicit_acquisition_error_and_context_closes() -> None:
    sdk = FakeSdk()
    sdk.results["snapshot"] = [(1, "permission denied")]

    with pytest.raises(FutuProviderError, match="market_snapshots.*ret_code=1"):
        _adapter(sdk).market_snapshots(["US.AAA"])

    assert sdk.contexts[0].closed is True


def test_temporary_provider_failure_retries_but_is_bounded() -> None:
    sdk = FakeSdk()
    sdk.results["snapshot"] = [
        (1, "temporary network error"),
        _ok({"rows": [{"code": "US.AAA"}]}),
    ]
    clock = FakeClock()

    result = _adapter(sdk, clock).market_snapshots(["US.AAA"])

    assert len(result) == 1
    assert sdk.snapshot_requests == [("US.AAA",), ("US.AAA",)]
    assert clock.sleeps == [1.0]
    assert sdk.contexts[0].closed is True


def test_retry_exhaustion_never_returns_an_empty_success_and_closes_context() -> None:
    sdk = FakeSdk()
    sdk.results["snapshot"] = [(1, "temporary network error")] * 3

    with pytest.raises(FutuProviderError, match="FUTU_RATE_LIMIT_RETRY_EXHAUSTED"):
        _adapter(sdk).market_snapshots(["US.AAA"])

    assert len(sdk.snapshot_requests) == 3
    assert sdk.contexts[0].closed is True


def test_context_closes_when_the_sdk_raises() -> None:
    sdk = FakeSdk()
    sdk.results["plate"] = [RuntimeError("socket closed")]

    with pytest.raises(RuntimeError, match="socket closed"):
        _adapter(sdk).owner_plates(["US.AAA"])

    assert sdk.contexts[0].closed is True


def test_market_snapshot_batches_400_400_and_remainder() -> None:
    sdk = FakeSdk()
    codes = [f"US.{index:04d}" for index in range(850)]
    sdk.results["snapshot"] = [_ok({"rows": []})] * 3

    batches = _adapter(sdk).market_snapshots(codes)

    assert [len(request) for request in sdk.snapshot_requests] == [400, 400, 50]
    assert [batch.batch_index for batch in batches] == [1, 2, 3]


def test_market_states_batches_400_400_and_remainder_with_raw_unknown_values() -> None:
    sdk = FakeSdk()
    codes = [f"US.{index:04d}" for index in range(850)]
    sdk.results["market_state"] = [
        _ok({"rows": [{"code": "US.0000", "stock_name": None, "market_state": "NEW_STATE"}]}),
        _ok({"rows": []}),
        _ok({"rows": []}),
    ]

    batches = _adapter(sdk).market_states(codes)

    assert [len(request) for request in sdk.market_state_requests] == [400, 400, 50]
    assert [batch.batch_index for batch in batches] == [1, 2, 3]
    assert batches[0].endpoint == "market_states"
    assert batches[0].raw_response["rows"][0] == {
        "code": "US.0000",
        "stock_name": None,
        "market_state": "NEW_STATE",
    }
    assert all(context.closed for context in sdk.contexts)


def test_market_states_provider_error_closes_context() -> None:
    sdk = FakeSdk()
    sdk.results["market_state"] = [(1, "permission denied")]

    with pytest.raises(FutuProviderError, match="market_states.*ret_code=1"):
        _adapter(sdk).market_states(["US.AAA"])

    assert sdk.contexts[0].closed is True


def test_owner_plates_batches_200_and_remainder() -> None:
    sdk = FakeSdk()
    codes = [f"US.{index:04d}" for index in range(250)]
    sdk.results["plate"] = [_ok({"rows": []})] * 2

    _adapter(sdk).owner_plates(codes)

    assert [len(request) for request in sdk.plate_requests] == [200, 50]


def test_market_snapshot_rate_limit_is_60_requests_per_30_seconds() -> None:
    sdk = FakeSdk()
    sdk.results["snapshot"] = [_ok({"rows": []})] * 61
    clock = FakeClock()
    adapter = _adapter(sdk, clock)

    for _ in range(61):
        adapter.market_snapshots(["US.AAA"])

    assert len(sdk.snapshot_requests) == 61
    assert clock.sleeps == [30.0]


def test_market_state_rate_limit_is_10_requests_per_30_seconds() -> None:
    sdk = FakeSdk()
    sdk.results["market_state"] = [_ok({"rows": []})] * 11
    clock = FakeClock()
    adapter = _adapter(sdk, clock)

    for _ in range(11):
        adapter.market_states(["US.AAA"])

    assert len(sdk.market_state_requests) == 11
    assert clock.sleeps == [30.0]


def test_market_state_limiter_is_independent_from_market_snapshot_limiter() -> None:
    sdk = FakeSdk()
    sdk.results["market_state"] = [_ok({"rows": []})] * 10
    sdk.results["snapshot"] = [_ok({"rows": []})]
    clock = FakeClock()
    adapter = _adapter(sdk, clock)

    for _ in range(10):
        adapter.market_states(["US.AAA"])
    adapter.market_snapshots(["US.AAA"])

    assert clock.sleeps == []
    assert len(sdk.snapshot_requests) == 1


def test_market_snapshots_preserve_real_rows_without_synthetic_freshness_fields() -> None:
    sdk = FakeSdk()
    sdk.results["snapshot"] = [
        _ok({
            "rows": [{
                "code": "US.AAA",
                "update_time": "2026-08-21 10:24:27",
                "sec_status": "NORMAL",
                "suspension": None,
            }]
        })
    ]

    row = _adapter(sdk).market_snapshots(["US.AAA"])[0].raw_response["rows"][0]

    assert row["update_time"] == "2026-08-21 10:24:27"
    assert row["sec_status"] == "NORMAL"
    assert row["suspension"] is None
    assert {"market_data_delay_class", "regular_session_complete", "market_session"}.isdisjoint(row)


def test_collect_runtime_evidence_records_sdk_global_state_and_one_qot_right_event() -> None:
    sdk = FakeSdk()
    sdk.results["global_state"] = [_ok({"server_ver": "1009", "market_us": "MORNING"})]
    sdk.notifications = [[("QOT_RIGHT", "UNCHANGED", {"us_qot_right": "NEW_RIGHT", "cn_qot_right": "CN"})]]
    clock = FakeClock()

    batches = _adapter(sdk, clock).collect_runtime_evidence(notification_window_seconds=0.5)

    assert [batch.endpoint for batch in batches] == [
        "runtime_sdk_version",
        "global_state",
        "qot_right_capture",
    ]
    assert batches[0].raw_response == {"sdk_version": "10.09.6908"}
    assert batches[1].raw_response == {"server_ver": "1009", "market_us": "MORNING"}
    assert batches[2].raw_request == {"notification_window_seconds": {"__float_repr__": "0.5"}}
    assert batches[2].raw_response == {
        "events": ({
            "notify_type": "QOT_RIGHT",
            "sub_type": "UNCHANGED",
            "msg": {"us_qot_right": "NEW_RIGHT", "cn_qot_right": "CN"},
        },)
    }
    assert clock.sleeps == [0.5]
    assert sdk.global_state_requests == 1
    assert sdk.contexts[0].closed is True


def test_collect_runtime_evidence_preserves_event_order_unknown_values_and_empty_observations() -> None:
    sdk = FakeSdk()
    sdk.results["global_state"] = [_ok({"server_ver": "1009"}), _ok({"server_ver": "1010"})]
    sdk.notifications = [
        [
            ("QOT_RIGHT", "FIRST", {"us_qot_right": "UNKNOWN_NEW_VALUE"}),
            ("QOT_RIGHT", "SECOND", {"us_qot_right": None}),
        ],
        [],
    ]
    adapter = _adapter(sdk)

    first = adapter.collect_runtime_evidence(notification_window_seconds=0)
    second = adapter.collect_runtime_evidence(notification_window_seconds=0)

    assert [event["sub_type"] for event in first[2].raw_response["events"]] == ["FIRST", "SECOND"]
    assert first[2].raw_response["events"][0]["msg"]["us_qot_right"] == "UNKNOWN_NEW_VALUE"
    assert first[2].raw_response["events"][1]["msg"]["us_qot_right"] is None
    assert second[2].raw_response == {"events": ()}
    assert first[1].response_hash != second[1].response_hash
    assert all(context.closed for context in sdk.contexts)


def test_runtime_evidence_hashes_are_deterministic_and_sensitive_to_sdk_window_and_events() -> None:
    def evidence(*, sdk_version: str, window: float, right: str) -> tuple[RawApiBatch, ...]:
        sdk = FakeSdk()
        sdk.__version__ = sdk_version
        sdk.results["global_state"] = [_ok({"server_ver": "1009"})]
        sdk.notifications = [[("QOT_RIGHT", "EVENT", {"us_qot_right": right})]]
        return _adapter(sdk).collect_runtime_evidence(notification_window_seconds=window)

    first = evidence(sdk_version="10.09.6908", window=1.0, right="RIGHT_A")
    same = evidence(sdk_version="10.09.6908", window=1.0, right="RIGHT_A")
    changed_sdk = evidence(sdk_version="10.10.7008", window=1.0, right="RIGHT_A")
    changed_window = evidence(sdk_version="10.09.6908", window=2.0, right="RIGHT_A")
    changed_event = evidence(sdk_version="10.09.6908", window=1.0, right="RIGHT_B")

    assert [batch.response_hash for batch in first] == [batch.response_hash for batch in same]
    assert first[0].response_hash != changed_sdk[0].response_hash
    assert first[2].request_hash != changed_window[2].request_hash
    assert first[2].response_hash != changed_event[2].response_hash


def test_collect_runtime_evidence_requires_a_nonnegative_explicit_window_and_closes_on_error() -> None:
    sdk = FakeSdk()
    adapter = _adapter(sdk)

    for invalid_window in (-1, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="notification_window_seconds"):
            adapter.collect_runtime_evidence(notification_window_seconds=invalid_window)

    sdk.results["global_state"] = [(1, "permission denied")]
    with pytest.raises(FutuProviderError, match="global_state.*ret_code=1"):
        adapter.collect_runtime_evidence(notification_window_seconds=0)

    assert sdk.contexts[0].closed is True


def test_collect_runtime_evidence_closes_context_when_handler_registration_fails() -> None:
    sdk = FakeSdk()
    sdk.handler_result = 1

    with pytest.raises(FutuProviderError, match="QOT_RIGHT handler"):
        _adapter(sdk).collect_runtime_evidence(notification_window_seconds=0)

    assert sdk.global_state_requests == 0
    assert sdk.contexts[0].closed is True


def test_owner_plate_rate_limit_is_10_requests_per_30_seconds() -> None:
    sdk = FakeSdk()
    sdk.results["plate"] = [_ok({"rows": []})] * 11
    clock = FakeClock()
    adapter = _adapter(sdk, clock)

    for _ in range(11):
        adapter.owner_plates(["US.AAA"])

    assert len(sdk.plate_requests) == 11
    assert clock.sleeps == [30.0]


def test_screen_pagination_rate_limit_is_10_requests_per_30_seconds() -> None:
    sdk = FakeSdk()
    sdk.results["screen"] = [(0, (True, 0, []))] * 11
    clock = FakeClock()
    adapter = _adapter(sdk, clock)

    for _ in range(11):
        adapter.screen_all_pages()

    assert len(sdk.screen_requests) == 11
    assert clock.sleeps == [30.0]


def test_market_and_owner_limiters_are_independent() -> None:
    sdk = FakeSdk()
    sdk.results["snapshot"] = [_ok({"rows": []})] * 60
    sdk.results["plate"] = [_ok({"rows": []})]
    clock = FakeClock()
    adapter = _adapter(sdk, clock)

    for _ in range(60):
        adapter.market_snapshots(["US.AAA"])
    adapter.owner_plates(["US.AAA"])

    assert clock.sleeps == []
    assert len(sdk.plate_requests) == 1


def test_adapter_has_no_universe_or_detector_business_owner() -> None:
    source = Path(
        "src/tv_quant/pattern_finder/universe_foundation/futu_adapter.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_names = {
        "evaluate_security",
        "resolve_classification",
        "build_funnel",
        "SecurityEvaluationPrerequisites",
        "QualifiedActiveStatusMapping",
        "FutuUniverseGateway",
        "GatewayAttempt",
        "UniverseSnapshot",
        "UniverseSnapshotStore",
        "detect_flat_base",
        "UNIVERSE_FRESHNESS_BLOCKER",
        "market_data_delay_class",
    }

    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    definitions = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    imports = {
        alias.asname or alias.name.rsplit(".", maxsplit=1)[-1]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert names.isdisjoint(forbidden_names)
    assert definitions.isdisjoint(forbidden_names)
    assert imports.isdisjoint(forbidden_names)
    assert "streamlit" not in source.lower()
