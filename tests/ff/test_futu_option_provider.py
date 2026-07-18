from __future__ import annotations

import ast
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Callable

import pytest

from tv_quant.ff.models import OptionLeg
from tv_quant.ff.futu_provider import FutuOptionProvider, IncompleteOptionChainError


FIXTURE = Path("tests/fixtures/ff/futu_option_chain.json")
PROVIDER_SOURCE = Path("src/tv_quant/ff/futu_provider.py")
MISSING = object()


class FakeQuoteContext:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.called_methods: set[str] = set()
        self.calls: defaultdict[str, int] = defaultdict(int)
        self.failures: defaultdict[str, list[BaseException]] = defaultdict(list)
        self.responses: defaultdict[str, list[tuple[object, object]]] = defaultdict(list)
        self.close_calls = 0

    @classmethod
    def from_fixture(cls, path: Path = FIXTURE) -> FakeQuoteContext:
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def fail_next(self, method: str, *errors: BaseException) -> None:
        self.failures[method].extend(errors)

    def respond_next(self, method: str, *responses: tuple[object, object]) -> None:
        self.responses[method].extend(responses)

    def _before(self, method: str) -> tuple[object, object] | None:
        self.called_methods.add(method)
        self.calls[method] += 1
        if self.failures[method]:
            raise self.failures[method].pop(0)
        if self.responses[method]:
            return self.responses[method].pop(0)
        return None

    def get_global_state(self) -> tuple[int, dict[str, Any]]:
        response = self._before("get_global_state")
        if response is not None:
            return response  # type: ignore[return-value]
        return 0, self.payload["global_state"]

    def get_option_expiration_date(self, code: str) -> tuple[int, list[dict[str, Any]]]:
        response = self._before("get_option_expiration_date")
        if response is not None:
            return response  # type: ignore[return-value]
        rows = [row for row in self.payload["expiries"] if row["code"] == code]
        return 0, rows

    def get_option_chain(
        self, code: str, *, start: str, end: str
    ) -> tuple[int, list[dict[str, Any]]]:
        response = self._before("get_option_chain")
        if response is not None:
            return response  # type: ignore[return-value]
        assert code == "US.SPY"
        assert start == end
        return 0, self.payload["chains"].get(start, [])

    def get_market_snapshot(self, codes: list[str]) -> tuple[int, list[dict[str, Any]]]:
        response = self._before("get_market_snapshot")
        if response is not None:
            return response  # type: ignore[return-value]
        requested = set(codes)
        rows = [row for row in self.payload["snapshots"] if row["code"] in requested]
        return 0, rows

    def close(self) -> None:
        self.close_calls += 1


def make_provider(
    fake: FakeQuoteContext,
    *,
    sleeps: list[float] | None = None,
    jitter: Callable[[], float] = lambda: 0.0,
) -> FutuOptionProvider:
    recorded_sleeps = sleeps if sleeps is not None else []
    return FutuOptionProvider(
        quote_context_factory=lambda: fake,
        ret_ok=0,
        ready_status="READY",
        sleep=recorded_sleeps.append,
        jitter=jitter,
    )


def test_provider_uses_only_quote_context_and_normalizes_iv() -> None:
    fake = FakeQuoteContext.from_fixture()
    provider = make_provider(fake)

    rows = provider.get_option_snapshot("SPY", date(2026, 9, 18))

    assert isinstance(rows[0], OptionLeg)
    assert rows[0].iv == pytest.approx(0.14794)
    assert rows[0].raw_iv == pytest.approx(14.794)
    assert rows[0].raw_iv_unit == "percent"
    assert rows[0].contract_symbol == "US.SPY260918C600000"
    assert fake.called_methods <= {
        "get_global_state",
        "get_option_expiration_date",
        "get_option_chain",
        "get_market_snapshot",
    }


def test_expiries_are_parsed_as_dates() -> None:
    provider = make_provider(FakeQuoteContext.from_fixture())

    assert provider.get_expiries("spy") == [date(2026, 9, 18), date(2026, 10, 16)]


@pytest.mark.parametrize(
    "qot_logined",
    [
        pytest.param(MISSING, id="missing"),
        pytest.param(False, id="false"),
        pytest.param(0, id="zero"),
        pytest.param(1, id="integer-one"),
        pytest.param("1", id="string-one"),
        pytest.param("true", id="string-true"),
        pytest.param(None, id="none"),
    ],
)
def test_opend_requires_exact_boolean_true(qot_logined: object) -> None:
    fake = FakeQuoteContext.from_fixture()
    state: dict[str, object] = {"program_status_type": "READY"}
    if qot_logined is not MISSING:
        state["qot_logined"] = qot_logined
    fake.payload["global_state"] = state

    with pytest.raises(RuntimeError, match="OpenD is unavailable"):
        make_provider(fake).get_expiries("SPY")

    assert fake.calls["get_option_expiration_date"] == 0


@pytest.mark.parametrize("program_status_type", ["STARTING", None, 1])
def test_opend_requires_the_injected_ready_status_exactly(
    program_status_type: object,
) -> None:
    fake = FakeQuoteContext.from_fixture()
    fake.payload["global_state"] = {
        "qot_logined": True,
        "program_status_type": program_status_type,
    }

    with pytest.raises(RuntimeError, match="OpenD is unavailable"):
        make_provider(fake).get_expiries("SPY")

    assert fake.calls["get_option_expiration_date"] == 0


def test_timeout_retries_are_bounded_counted_and_backed_off() -> None:
    fake = FakeQuoteContext.from_fixture()
    fake.fail_next("get_option_expiration_date", TimeoutError(), TimeoutError())
    sleeps: list[float] = []
    provider = make_provider(fake, sleeps=sleeps, jitter=lambda: 0.125)

    assert provider.get_expiries("SPY")

    assert fake.calls["get_option_expiration_date"] == 3
    assert sleeps == [0.625, 1.125]
    assert provider.metrics.request_count == 4
    assert provider.metrics.retry_count == 2
    assert provider.metrics.method_counts == {
        "get_global_state": 1,
        "get_option_expiration_date": 3,
    }


def test_timeout_stops_after_four_attempts() -> None:
    fake = FakeQuoteContext.from_fixture()
    fake.fail_next("get_option_chain", *(TimeoutError() for _ in range(4)))
    sleeps: list[float] = []
    provider = make_provider(fake, sleeps=sleeps)

    with pytest.raises(TimeoutError):
        provider.get_option_snapshot("SPY", date(2026, 9, 18))

    assert fake.calls["get_option_chain"] == 4
    assert sleeps == [0.5, 1.0, 2.0]
    assert provider.metrics.retry_count == 3


@pytest.mark.parametrize(
    "timeout_message",
    [
        pytest.param("PacketErr.Timeout", id="query-timeout"),
        pytest.param("Abnormal event timeout", id="event-timeout"),
        pytest.param("Connect timeout", id="connect-timeout"),
    ],
)
def test_real_futu_non_ok_timeout_results_are_retried(timeout_message: str) -> None:
    fake = FakeQuoteContext.from_fixture()
    fake.respond_next(
        "get_option_expiration_date",
        (-1, timeout_message),
        (-1, timeout_message),
    )
    sleeps: list[float] = []
    provider = make_provider(fake, sleeps=sleeps)

    assert provider.get_expiries("SPY")

    assert fake.calls["get_option_expiration_date"] == 3
    assert sleeps == [0.5, 1.0]
    assert provider.metrics.request_count == 4
    assert provider.metrics.retry_count == 2


def test_real_futu_non_ok_timeout_stops_after_exactly_four_attempts() -> None:
    fake = FakeQuoteContext.from_fixture()
    fake.respond_next(
        "get_option_expiration_date",
        *((-1, "PacketErr.Timeout") for _ in range(4)),
    )
    sleeps: list[float] = []
    provider = make_provider(fake, sleeps=sleeps)

    with pytest.raises(TimeoutError, match="get_option_expiration_date"):
        provider.get_expiries("SPY")

    assert fake.calls["get_option_expiration_date"] == 4
    assert sleeps == [0.5, 1.0, 2.0]
    assert provider.metrics.request_count == 5
    assert provider.metrics.retry_count == 3


def test_arbitrary_non_ok_result_fails_immediately_without_retry() -> None:
    fake = FakeQuoteContext.from_fixture()
    fake.respond_next("get_option_expiration_date", (-1, "temporary provider failure"))
    sleeps: list[float] = []
    provider = make_provider(fake, sleeps=sleeps)

    with pytest.raises(RuntimeError, match="temporary provider failure"):
        provider.get_expiries("SPY")

    assert fake.calls["get_option_expiration_date"] == 1
    assert sleeps == []
    assert provider.metrics.request_count == 2
    assert provider.metrics.retry_count == 0


@pytest.mark.parametrize(
    "invalid_jitter",
    [
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
        pytest.param(-0.001, id="negative"),
        pytest.param("not-a-number", id="nonnumeric"),
        pytest.param(None, id="none"),
    ],
)
def test_invalid_retry_jitter_fails_without_counting_or_sleeping(
    invalid_jitter: object,
) -> None:
    fake = FakeQuoteContext.from_fixture()
    fake.fail_next("get_option_expiration_date", TimeoutError())
    sleeps: list[float] = []
    provider = make_provider(
        fake,
        sleeps=sleeps,
        jitter=lambda: invalid_jitter,  # type: ignore[return-value]
    )

    with pytest.raises(ValueError, match="retry jitter must be finite and non-negative"):
        provider.get_expiries("SPY")

    assert provider.metrics.retry_count == 0
    assert sleeps == []
    assert fake.calls["get_option_expiration_date"] == 1


def test_snapshot_calls_have_zero_subscription_and_historical_quota_impact() -> None:
    provider = make_provider(FakeQuoteContext.from_fixture())

    provider.get_option_snapshot("SPY", date(2026, 9, 18))

    assert provider.metrics.subscription_request_count == 0
    assert provider.metrics.historical_quota_request_count == 0
    assert provider.metrics.snapshot_request_count == 1


def test_underlying_option_volume_sums_all_expiries() -> None:
    provider = make_provider(FakeQuoteContext.from_fixture())

    assert provider.get_underlying_option_volume("SPY") == 1350


def test_market_snapshot_requires_every_requested_code_exactly_once() -> None:
    fake = FakeQuoteContext.from_fixture()
    fake.payload["snapshots"] = fake.payload["snapshots"][1:]
    provider = make_provider(fake)

    with pytest.raises(
        IncompleteOptionChainError,
        match="incomplete option chain",
    ):
        provider.get_option_snapshot("SPY", date(2026, 9, 18))


def test_market_snapshot_rejects_duplicate_returned_codes() -> None:
    fake = FakeQuoteContext.from_fixture()
    fake.payload["snapshots"].append(dict(fake.payload["snapshots"][0]))
    provider = make_provider(fake)

    with pytest.raises(
        IncompleteOptionChainError,
        match="incomplete option chain",
    ):
        provider.get_option_snapshot("SPY", date(2026, 9, 18))


def test_market_snapshot_rejects_an_unexpected_returned_code() -> None:
    fake = FakeQuoteContext.from_fixture()
    requested_rows = [
        row for row in fake.payload["snapshots"] if row["strike_time"] == "2026-09-18"
    ]
    unexpected = dict(requested_rows[0], code="US.SPY260918C999000")
    fake.respond_next("get_market_snapshot", (0, requested_rows + [unexpected]))
    provider = make_provider(fake)

    with pytest.raises(
        IncompleteOptionChainError,
        match="incomplete option chain",
    ):
        provider.get_option_snapshot("SPY", date(2026, 9, 18))


@pytest.mark.parametrize(
    "invalid_code",
    [
        pytest.param(None, id="null"),
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace"),
        pytest.param(123, id="non-string"),
    ],
)
def test_chain_code_must_be_a_real_nonempty_string_before_snapshot_request(
    invalid_code: object,
) -> None:
    fake = FakeQuoteContext.from_fixture()
    chain_rows = fake.payload["chains"]["2026-09-18"]
    snapshot_rows = [
        row for row in fake.payload["snapshots"] if row["strike_time"] == "2026-09-18"
    ]
    chain_rows[0]["code"] = invalid_code
    snapshot_rows[0]["code"] = invalid_code
    fake.respond_next("get_market_snapshot", (0, snapshot_rows))

    with pytest.raises(IncompleteOptionChainError, match="invalid chain code"):
        make_provider(fake).get_option_snapshot("SPY", date(2026, 9, 18))

    assert fake.calls["get_market_snapshot"] == 0


@pytest.mark.parametrize(
    "invalid_owner",
    [
        pytest.param(MISSING, id="missing"),
        pytest.param(None, id="null"),
        pytest.param(123, id="non-string"),
        pytest.param("SPY", id="missing-market-prefix"),
        pytest.param("US.QQQ", id="wrong-owner"),
    ],
)
def test_chain_owner_must_match_the_requested_canonical_market_code(
    invalid_owner: object,
) -> None:
    fake = FakeQuoteContext.from_fixture()
    chain_row = fake.payload["chains"]["2026-09-18"][0]
    if invalid_owner is MISSING:
        chain_row.pop("stock_owner")
    else:
        chain_row["stock_owner"] = invalid_owner

    with pytest.raises(IncompleteOptionChainError, match="chain owner identity mismatch"):
        make_provider(fake).get_option_snapshot("SPY", date(2026, 9, 18))

    assert fake.calls["get_market_snapshot"] == 0


@pytest.mark.parametrize(
    "invalid_strike_time",
    [
        pytest.param(MISSING, id="missing"),
        pytest.param(None, id="null"),
        pytest.param(20260918, id="non-string"),
        pytest.param("not-a-date", id="malformed"),
        pytest.param("2026-10-16", id="wrong-expiry"),
    ],
)
def test_chain_expiry_must_parse_and_equal_the_requested_expiry(
    invalid_strike_time: object,
) -> None:
    fake = FakeQuoteContext.from_fixture()
    chain_row = fake.payload["chains"]["2026-09-18"][0]
    if invalid_strike_time is MISSING:
        chain_row.pop("strike_time")
    else:
        chain_row["strike_time"] = invalid_strike_time

    with pytest.raises(IncompleteOptionChainError, match="chain expiry identity mismatch"):
        make_provider(fake).get_option_snapshot("SPY", date(2026, 9, 18))

    assert fake.calls["get_market_snapshot"] == 0


@pytest.mark.parametrize(
    "invalid_code",
    [
        pytest.param(None, id="null"),
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace"),
        pytest.param(123, id="non-string"),
    ],
)
def test_snapshot_code_must_be_a_real_nonempty_string(invalid_code: object) -> None:
    fake = FakeQuoteContext.from_fixture()
    snapshot_rows = [
        row for row in fake.payload["snapshots"] if row["strike_time"] == "2026-09-18"
    ]
    snapshot_rows[0]["code"] = invalid_code
    fake.respond_next("get_market_snapshot", (0, snapshot_rows))

    with pytest.raises(IncompleteOptionChainError, match="invalid snapshot code"):
        make_provider(fake).get_option_snapshot("SPY", date(2026, 9, 18))


def test_snapshot_code_identity_must_match_the_requested_validated_multiset() -> None:
    fake = FakeQuoteContext.from_fixture()
    snapshot_rows = [
        row for row in fake.payload["snapshots"] if row["strike_time"] == "2026-09-18"
    ]
    snapshot_rows[0]["code"] = "US.QQQ260918C600000"
    fake.respond_next("get_market_snapshot", (0, snapshot_rows))

    with pytest.raises(IncompleteOptionChainError, match="snapshot identity mismatch"):
        make_provider(fake).get_option_snapshot("SPY", date(2026, 9, 18))


def test_provider_context_manager_closes_once_without_extra_quote_calls() -> None:
    fake = FakeQuoteContext.from_fixture()
    provider = make_provider(fake)

    with provider as opened:
        assert opened is provider
        assert opened.get_expiries("SPY")

    provider.close()

    assert fake.close_calls == 1
    assert fake.called_methods == {"get_global_state", "get_option_expiration_date"}


def test_readiness_failure_closes_the_new_context() -> None:
    fake = FakeQuoteContext.from_fixture()
    fake.payload["global_state"]["qot_logined"] = False
    provider = make_provider(fake)

    with pytest.raises(RuntimeError, match="OpenD is unavailable"):
        provider.get_expiries("SPY")

    assert fake.close_calls == 1
    assert fake.called_methods == {"get_global_state"}


def test_ff_package_contains_no_trade_context_names() -> None:
    source = PROVIDER_SOURCE.read_text(encoding="utf-8")
    forbidden = ("OpenSecTradeContext", "OpenUSTradeContext", "place_order")

    assert all(name not in source for name in forbidden)


def test_futu_import_is_local_and_quote_only() -> None:
    tree = ast.parse(PROVIDER_SOURCE.read_text(encoding="utf-8"))
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "futu"
    ]

    assert imports
    for node in imports:
        assert {alias.name for alias in node.names} <= {
            "OpenQuoteContext",
            "ProgramStatusType",
            "RET_OK",
        }
        owner = parent.get(node)
        while owner is not None and not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owner = parent.get(owner)
        assert isinstance(owner, ast.FunctionDef)
        assert owner.name == "_default_quote_context_factory"
