"""Paste the whole file into Futubull Quant's Python strategy editor.

Run HISTORY BACKTEST, one trigger symbol (SPY), once per 5-minute bar.
This probe only reads data and prints JSON; it contains no order/account API.
Local tests use stubs and do not certify compatibility with the platform.
"""

import json
import math
from datetime import timezone


class Strategy(StrategyBase):
    def initialize(self):
        declare_strategy_type(AlgoStrategyType.SECURITY)
        # Declare this directly in initialize so the backtest wizard can
        # discover it even when it does not execute helper methods first.
        self.运行标的1 = declare_trig_symbol()
        self.symbol = self.运行标的1
        self.custom_indicator()
        self.global_variables()
        self.emit({"event": "START", "version": "data-probe-v1",
                   "qualification": "NOT_VERIFIED", "orders_enabled": False})

    def trigger_symbols(self):
        pass

    def custom_indicator(self):
        pass

    def global_variables(self):
        self.last_trigger = None
        self.trigger_count = 0
        self.error_count = 0

    def emit(self, record):
        print("FUTU_DATA_PROBE " + json.dumps(record, ensure_ascii=True, allow_nan=False))

    def read_snapshot(self, bar_type):
        args = {"symbol": self.symbol, "bar_type": bar_type,
                "select": 2, "session_type": THType.RTH}
        record = {}
        issues = []
        readers = [("open", bar_open), ("high", bar_high), ("low", bar_low),
                   ("close", bar_close), ("volume", bar_volume)]
        for name, reader in readers:
            try:
                value = reader(**args)
                if isinstance(value, bool):
                    raise ValueError("boolean is not a market value")
                value = float(value)
                if not math.isfinite(value):
                    raise ValueError("nonfinite value")
                record[name] = value
            except Exception as exc:
                record[name] = None
                issues.append(name + ":" + type(exc).__name__)
        try:
            value = ema(period=20, data_type=DataType.CLOSE, **args)
            if isinstance(value, bool):
                raise ValueError("boolean indicator")
            value = float(value)
            if not math.isfinite(value) or value <= 0:
                raise ValueError("invalid indicator")
            record["ema20"] = value
        except Exception as exc:
            record["ema20"] = None
            issues.append("ema20:" + type(exc).__name__)
        prices = [record[k] for k in ("open", "high", "low", "close")]
        if all(v is not None for v in prices):
            o, h, low, c = prices
            if min(prices) <= 0 or not (low <= min(o, c) <= max(o, c) <= h):
                issues.append("INVALID_OHLC")
        if record["volume"] is not None and record["volume"] <= 0:
            issues.append("NEGATIVE_VOLUME" if record["volume"] < 0 else "ZERO_VOLUME_REVIEW")
        record["issues"] = issues
        record["select"] = 2
        record["source_bar_timestamp"] = None
        record["bar_completion"] = "NOT_VERIFIED"
        return record

    def handle_data(self):
        self.trigger_count += 1
        record = {"event": "SNAPSHOT", "trigger_count": self.trigger_count,
                  "qualification": "NOT_VERIFIED", "session": "RTH",
                  "adjustment": "PLATFORM_DYNAMIC_QFQ", "issues": []}
        try:
            clock = device_time(TimeZone.UTC)
            if clock.tzinfo is None or clock.utcoffset() is None:
                raise ValueError("timezone missing")
            clock = clock.astimezone(timezone.utc)
            record["trigger_time_utc"] = clock.isoformat()
            if self.last_trigger is not None and clock <= self.last_trigger:
                record["issues"].append("NONINCREASING_TRIGGER")
            else:
                self.last_trigger = clock
        except Exception as exc:
            record["trigger_time_utc"] = None
            record["issues"].append("CLOCK:" + type(exc).__name__)
        try:
            code = get_symbol_code(symbol=self.symbol)
            if code not in ("US.SPY", "US.QQQ"):
                raise ValueError("unsupported symbol")
            record["symbol"] = code
        except Exception as exc:
            record["issues"].append("SYMBOL:" + type(exc).__name__)
            self.error_count += 1
            record["error_count"] = self.error_count
            self.emit(record)
            return
        record["1m"] = self.read_snapshot(BarType.K_1M)
        record["5m"] = self.read_snapshot(BarType.K_5M)
        if record["issues"] or record["1m"]["issues"] or record["5m"]["issues"]:
            self.error_count += 1
        record["error_count"] = self.error_count
        self.emit(record)
