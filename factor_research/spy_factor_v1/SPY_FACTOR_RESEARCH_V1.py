class Strategy(StrategyBase):

    def initialize(self):
        declare_strategy_type(AlgoStrategyType.SECURITY)
        self.trigger_symbols()
        self.custom_indicator()
        self.global_variables()
        self.emit_factor("RUN_START", {
            "record": "START",
            "study_partition": "FUNCTIONAL_VALIDATION",
            "study_start_et": "2026-09-28",
            "study_end_et": "2026-10-06",
            "signal_start_et": "09:35",
            "signal_end_et": "14:55",
            "horizons_bars": "3,6,12",
            "formula": "close(select=2)>ema20(select=2)",
            "price_use": "NON_EXECUTABLE_CLOSE_TO_CLOSE",
            "orders_enabled": False,
            "volume_enabled": False,
            "fixture": False,
            "edge_claim": "PROHIBITED"
        })

    def trigger_symbols(self):
        self.trig_symbol_1 = declare_trig_symbol()

    def custom_indicator(self):
        pass

    def global_variables(self):
        self.factor_id = "SPY_F001_CLOSE_GT_EMA20"
        self.run_id = "SPY_F001_20260928_20261006_FV1"
        self.strategy_version = "SPY_FACTOR_RESEARCH_V1.1"
        self.strategy_hash = "20b794ad9bb14dc307d8be3d83a9b8a6a6050656d4e1d386e1a441e1c416d177"
        self.parameter_version = "F001-P1"
        self.study_start = 20260928
        self.study_end = 20261006
        self.signal_start_minute_et = 9 * 60 + 35
        self.signal_end_minute_et = 14 * 60 + 55
        self.summary_minute_et = 15 * 60 + 55
        self.last_trigger_key = ""
        self.current_day_et = ""
        self.current_day_number = 0
        self.pending = []
        self.day_returns = self.empty_returns()
        self.total_returns = self.empty_returns()
        self.day_event_count = 0
        self.day_error_count = 0
        self.completed_day_count = 0
        self.incomplete_day_count = 0
        self.total_error_count = 0

    def json_value(self, value):
        if value is True:
            return "true"
        if value is False:
            return "false"
        if value is None:
            return "null"
        if isinstance(value, (int, float)):
            return str(value)
        text = str(value)
        text = text.replace("\\", "\\\\").replace("\"", "\\\"")
        text = text.replace("\r", "\\r").replace("\n", "\\n")
        return "\"" + text + "\""

    def emit_factor(self, event_type, fields):
        payload = {
            "contract_version": "1.0",
            "event_type": event_type,
            "factor_id": self.factor_id,
            "run_id": self.run_id,
            "strategy_version": self.strategy_version,
            "strategy_hash": self.strategy_hash,
            "parameter_version": self.parameter_version,
            "symbol": "US.SPY",
            "timeframe": "5m",
            "bar_type": "K_5M",
            "select": 2,
            "session": "RTH",
            "timezone": "America/New_York"
        }
        payload.update(fields)
        parts = []
        for key in payload:
            parts.append(self.json_value(key) + ":" + self.json_value(payload[key]))
        print("FUTU_FACTOR_V1|{" + ",".join(parts) + "}")

    def empty_returns(self):
        return {
            "3_ALL": [], "3_PASS": [], "3_FAIL": [],
            "6_ALL": [], "6_PASS": [], "6_FAIL": [],
            "12_ALL": [], "12_PASS": [], "12_FAIL": []
        }

    def timestamp_text(self, value):
        return "%04d-%02d-%02dT%02d:%02d:%02d" % (
            value.year, value.month, value.day,
            value.hour, value.minute, value.second
        )

    def positive_number(self, value):
        if isinstance(value, bool):
            raise ValueError("BOOLEAN_VALUE")
        number = float(value)
        if number != number or number == float("inf") or number == float("-inf"):
            raise ValueError("NONFINITE_VALUE")
        if number <= 0:
            raise ValueError("NONPOSITIVE_VALUE")
        return number

    def number_text(self, value):
        return "%.10f" % value

    def emit_error(self, day_et, trigger_et, code, detail):
        self.day_error_count += 1
        self.total_error_count += 1
        self.emit_factor("ERROR", {
            "record": "ERROR",
            "session_date_et": day_et,
            "trigger_et": trigger_et,
            "code": code,
            "detail": detail,
            "edge_claim": "PROHIBITED"
        })

    def begin_day(self, day_number, day_et, trigger_et):
        if self.current_day_et != "" and len(self.pending) > 0:
            previous_count = len(self.pending)
            self.pending = []
            self.emit_error(
                self.current_day_et,
                trigger_et,
                "UNRESOLVED_PREVIOUS_DAY",
                str(previous_count)
            )
        self.current_day_number = day_number
        self.current_day_et = day_et
        self.day_returns = self.empty_returns()
        self.day_event_count = 0
        self.day_error_count = 0

    def append_return(self, horizon_bars, factor_state, result):
        all_key = str(horizon_bars) + "_ALL"
        state_key = str(horizon_bars) + "_" + factor_state
        self.day_returns[all_key].append(result)
        self.day_returns[state_key].append(result)
        self.total_returns[all_key].append(result)
        self.total_returns[state_key].append(result)

    def resolve_pending(self, day_number, minute_et, close_value, trigger_et, trigger_utc):
        remaining = []
        for item in self.pending:
            if item["day_number"] != day_number:
                self.emit_error(
                    self.current_day_et,
                    trigger_et,
                    "CROSS_DAY_PENDING_REJECTED",
                    item["event_id"]
                )
            elif item["due_minute_et"] < minute_et:
                self.emit_error(
                    self.current_day_et,
                    trigger_et,
                    "MISSED_OUTCOME_TIME",
                    item["event_id"] + "_H" + str(item["horizon_bars"])
                )
            elif item["due_minute_et"] == minute_et:
                result = close_value / item["signal_close"] - 1.0
                self.append_return(item["horizon_bars"], item["factor_state"], result)
                self.emit_factor("LABEL_MATURED", {
                    "record": "OUTCOME",
                    "signal_id": item["event_id"],
                    "event_id": item["event_id"],
                    "session_date_et": self.current_day_et,
                    "signal_time_et": item["signal_et"],
                    "signal_et": item["signal_et"],
                    "signal_time_utc": item["signal_utc"],
                    "signal_utc": item["signal_utc"],
                    "target_time_et": trigger_et,
                    "outcome_et": trigger_et,
                    "target_time_utc": trigger_utc,
                    "outcome_utc": trigger_utc,
                    "factor_value": item["factor_state"],
                    "factor_state": item["factor_state"],
                    "horizon": item["horizon_bars"],
                    "horizon_bars": item["horizon_bars"],
                    "horizon_minutes": item["horizon_bars"] * 5,
                    "signal_close": self.number_text(item["signal_close"]),
                    "target_close": self.number_text(close_value),
                    "future_close": self.number_text(close_value),
                    "forward_return": self.number_text(result),
                    "return": self.number_text(result),
                    "price_use": "NON_EXECUTABLE_CLOSE_TO_CLOSE",
                    "overlap_warning": True,
                    "edge_claim": "PROHIBITED"
                })
            else:
                remaining.append(item)
        self.pending = remaining

    def record_signal(self, day_number, minute_et, close_value, trigger_et, trigger_utc):
        try:
            ema20_value = self.positive_number(
                ema(
                    symbol=self.trig_symbol_1,
                    period=20,
                    data_type=DataType.CLOSE,
                    bar_type=BarType.K_5M,
                    select=2,
                    session_type=THType.RTH
                )
            )
        except Exception as exc:
            self.emit_error(
                self.current_day_et,
                trigger_et,
                "EMA20_READ_FAILED",
                type(exc).__name__
            )
            return

        factor_state = "PASS" if close_value > ema20_value else "FAIL"
        clock_hhmm = (minute_et // 60) * 100 + minute_et % 60
        event_id = self.current_day_et.replace("-", "") + "_" + ("%04d" % clock_hhmm)
        self.day_event_count += 1
        self.emit_factor("SIGNAL", {
            "record": "EVENT",
            "signal_id": event_id,
            "event_id": event_id,
            "session_date_et": self.current_day_et,
            "signal_time_et": trigger_et,
            "trigger_et": trigger_et,
            "signal_time_utc": trigger_utc,
            "trigger_utc": trigger_utc,
            "signal_close": self.number_text(close_value),
            "close": self.number_text(close_value),
            "ema20": self.number_text(ema20_value),
            "factor_value": factor_state,
            "factor_state": factor_state,
            "horizons_bars": "3,6,12",
            "price_use": "NON_EXECUTABLE_CLOSE_TO_CLOSE",
            "overlap_warning": True,
            "edge_claim": "PROHIBITED"
        })

        for horizon_bars in (3, 6, 12):
            self.pending.append({
                "event_id": event_id,
                "day_number": day_number,
                "signal_et": trigger_et,
                "signal_utc": trigger_utc,
                "signal_close": close_value,
                "factor_state": factor_state,
                "horizon_bars": horizon_bars,
                "due_minute_et": minute_et + horizon_bars * 5
            })

    def median_value(self, values):
        ordered = sorted(values)
        count = len(ordered)
        middle = count // 2
        if count % 2 == 1:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2.0

    def emit_summary_line(self, scope, returns, horizon_bars, group, trigger_et, trigger_utc):
        values = returns[str(horizon_bars) + "_" + group]
        all_values = returns[str(horizon_bars) + "_ALL"]
        count = len(values)
        if count == 0:
            mean_text = "NA"
            median_text = "NA"
            win_rate_text = "NA"
            delta_text = "NA"
        else:
            mean_value = sum(values) / count
            wins = 0
            for value in values:
                if value > 0:
                    wins += 1
            mean_text = self.number_text(mean_value)
            median_text = self.number_text(self.median_value(values))
            win_rate_text = self.number_text(float(wins) / count)
            if len(all_values) == 0:
                delta_text = "NA"
            else:
                baseline_mean = sum(all_values) / len(all_values)
                delta_text = self.number_text(mean_value - baseline_mean)
        self.emit_factor("SUMMARY", {
            "record": "SUMMARY",
            "scope": scope,
            "asof_et": trigger_et,
            "asof_utc": trigger_utc,
            "session_date_et": self.current_day_et,
            "factor": "CLOSE_GT_EMA20",
            "horizon_bars": horizon_bars,
            "horizon_minutes": horizon_bars * 5,
            "group": group,
            "n": count,
            "mean_return": mean_text,
            "median_return": median_text,
            "win_rate": win_rate_text,
            "delta_mean_vs_all": delta_text,
            "price_use": "NON_EXECUTABLE_CLOSE_TO_CLOSE",
            "overlap_warning": True,
            "independent_samples": False,
            "edge_claim": "PROHIBITED"
        })

    def emit_summaries(self, trigger_et, trigger_utc):
        complete = (
            self.day_event_count == 65
            and len(self.pending) == 0
            and self.day_error_count == 0
            and len(self.day_returns["3_ALL"]) == 65
            and len(self.day_returns["6_ALL"]) == 65
            and len(self.day_returns["12_ALL"]) == 65
        )
        if complete:
            self.completed_day_count += 1
        else:
            self.incomplete_day_count += 1
        self.emit_factor("DAY_STATUS", {
            "record": "DAY_STATUS",
            "session_date_et": self.current_day_et,
            "asof_et": trigger_et,
            "asof_utc": trigger_utc,
            "status": "COMPLETE" if complete else "INCOMPLETE",
            "event_count": self.day_event_count,
            "outcomes_h3": len(self.day_returns["3_ALL"]),
            "outcomes_h6": len(self.day_returns["6_ALL"]),
            "outcomes_h12": len(self.day_returns["12_ALL"]),
            "pending_count": len(self.pending),
            "error_count": self.day_error_count,
            "expected_events": 65,
            "edge_claim": "PROHIBITED"
        })
        for horizon_bars in (3, 6, 12):
            for group in ("ALL", "PASS", "FAIL"):
                self.emit_summary_line(
                    "DAY", self.day_returns, horizon_bars, group, trigger_et, trigger_utc
                )
                self.emit_summary_line(
                    "CUMULATIVE", self.total_returns, horizon_bars, group, trigger_et, trigger_utc
                )
        if self.current_day_number == self.study_end:
            run_complete = (
                self.completed_day_count == 7
                and self.incomplete_day_count == 0
                and self.total_error_count == 0
            )
            self.emit_factor("RUN_END", {
                "record": "RUN_END",
                "end_time_et": trigger_et,
                "end_time_utc": trigger_utc,
                "status": "COMPLETE" if run_complete else "INCOMPLETE",
                "completed_days": self.completed_day_count,
                "incomplete_days": self.incomplete_day_count,
                "signal_count": sum(1 for _ in self.total_returns["3_ALL"]),
                "labels_h3": len(self.total_returns["3_ALL"]),
                "labels_h6": len(self.total_returns["6_ALL"]),
                "labels_h12": len(self.total_returns["12_ALL"]),
                "error_count": self.total_error_count,
                "edge_claim": "PROHIBITED"
            })

    def handle_data(self):
        try:
            clock_et = device_time(TimeZone.ET)
            clock_utc = device_time(TimeZone.UTC)
            day_number = clock_et.year * 10000 + clock_et.month * 100 + clock_et.day
            day_et = "%04d-%02d-%02d" % (clock_et.year, clock_et.month, clock_et.day)
            minute_et = clock_et.hour * 60 + clock_et.minute
            trigger_et = self.timestamp_text(clock_et)
            trigger_utc = self.timestamp_text(clock_utc) + "Z"
        except Exception as exc:
            self.emit_factor("ERROR", {
                "record": "ERROR",
                "session_date_et": "UNKNOWN",
                "trigger_et": "UNKNOWN",
                "code": "CLOCK_READ_FAILED",
                "detail": type(exc).__name__,
                "edge_claim": "PROHIBITED"
            })
            return

        if day_number < self.study_start or day_number > self.study_end:
            return
        if minute_et < self.signal_start_minute_et or minute_et > self.summary_minute_et:
            return
        if minute_et % 5 != 0:
            return

        trigger_key = str(day_number) + "_" + str(minute_et)
        if trigger_key == self.last_trigger_key:
            return
        self.last_trigger_key = trigger_key

        if day_number != self.current_day_number:
            self.begin_day(day_number, day_et, trigger_et)

        try:
            symbol_code = get_symbol_code(symbol=self.trig_symbol_1)
            if symbol_code != "US.SPY":
                raise ValueError("SYMBOL_NOT_SPY")
        except Exception as exc:
            self.emit_error(day_et, trigger_et, "SYMBOL_CHECK_FAILED", type(exc).__name__)
            return

        try:
            close_value = self.positive_number(
                bar_close(
                    symbol=self.trig_symbol_1,
                    bar_type=BarType.K_5M,
                    select=2,
                    session_type=THType.RTH
                )
            )
        except Exception as exc:
            self.emit_error(day_et, trigger_et, "CLOSE_READ_FAILED", type(exc).__name__)
            return

        self.resolve_pending(day_number, minute_et, close_value, trigger_et, trigger_utc)

        if self.signal_start_minute_et <= minute_et <= self.signal_end_minute_et:
            self.record_signal(day_number, minute_et, close_value, trigger_et, trigger_utc)

        if minute_et == self.summary_minute_et:
            self.emit_summaries(trigger_et, trigger_utc)
