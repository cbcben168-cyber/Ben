class Strategy(StrategyBase):

    def initialize(self):
        declare_strategy_type(AlgoStrategyType.SECURITY)
        self.trigger_symbols()
        self.custom_indicator()
        self.global_variables()
        self.emit_batch("RUN_START", {
            "record": "START",
            "study_partition": "TRAIN",
            "system_start_target_et": "2025-07-01",
            "sensitivity_start_et": "2025-09-02",
            "study_start_et": "2025-10-01",
            "study_end_et": "2026-06-30",
            "signal_start_et": "09:35",
            "signal_end_et": "14:55",
            "early_close_signal_end_et": "11:55",
            "early_close_dates_et": "2025-11-28,2025-12-24",
            "expected_sessions": 187,
            "expected_factor_events": 12083,
            "expected_labels": 36249,
            "expected_warmup_bars": 4956,
            "horizons_bars": "3,6,12",
            "factor_ids": self.factor_ids,
            "definition_hash": self.definition_hash,
            "price_use": "NON_EXECUTABLE_CLOSE_TO_CLOSE",
            "warmup_audit": "DUAL_RECURSIVE_EMA20_V1",
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
        self.batch_id = "SPY_C1_BATCH_TRAIN_20251001_20260630_V1"
        self.run_id = self.batch_id
        self.strategy_version = "FUTU_BATCH_FACTORS_TRAIN_V1"
        self.strategy_hash = "548a449d4811386adf90731e9ec3c753cf4ed5b74cae33ef35b3e60ea7871420"
        self.parameter_version = "C1-SIX-FACTOR-TRAIN-20251001-20260630-V1"
        self.definition_hash = "370c846144bf3e184642acd4a55c97976c75c377073a74f43aa001fef758be23"
        self.factor_ids = (
            "SPY_F001_CLOSE_GT_EMA20,"
            "SPY_F002_EMA20_RISING_3,"
            "SPY_F003_CLOSE_CROSS_ABOVE_EMA20,"
            "SPY_F004_CLOSE_BREAKS_PRIOR_5_HIGH,"
            "SPY_F005_THREE_CLOSE_MOMENTUM,"
            "SPY_F006_STRONG_BULL_BODY"
        )
        self.system_start_target = 20250701
        self.sensitivity_start = 20250902
        self.study_start = 20251001
        self.study_end = 20260630
        self.expected_session_count = 187
        self.expected_factor_event_count = 12083
        self.expected_label_count = 36249
        self.expected_warmup_bar_count = 4956
        self.signal_start_minute_et = 9 * 60 + 35
        self.signal_end_minute_et = 14 * 60 + 55
        self.summary_minute_et = 15 * 60 + 55
        self.market_close_minute_et = 16 * 60
        self.early_close_signal_end_minute_et = 11 * 60 + 55
        self.early_close_summary_minute_et = 12 * 60 + 55
        self.early_close_market_close_minute_et = 13 * 60
        self.early_close_days = {20251128: True, 20251224: True}
        self.warmup_early_close_days = {20250703: True}
        self.last_trigger_key = ""
        self.current_day_et = ""
        self.current_day_number = 0
        self.pending = []
        self.day_signal_count = 0
        self.day_event_count = 0
        self.day_invalid_f006_count = 0
        self.day_error_count = 0
        self.completed_day_count = 0
        self.incomplete_day_count = 0
        self.total_signal_count = 0
        self.total_event_count = 0
        self.total_error_count = 0
        self.first_observation_et = ""
        self.long_ema20 = None
        self.short_ema20 = None
        self.long_ema_history = []
        self.short_ema_history = []
        self.warmup_close_history = []
        self.long_bar_count = 0
        self.short_bar_count = 0
        self.pre_study_long_bar_count = None
        self.warmup_audit_emitted = False
        self.warmup_audit_status = "NOT_CHECKED"
        self.platform_long_mismatches = {"f001": 0, "f002": 0, "f003": 0}
        self.long_short_mismatches = {"f001": 0, "f002": 0, "f003": 0}

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

    def emit_batch(self, event_type, fields):
        payload = {
            "contract_version": "2.0",
            "event_type": event_type,
            "batch_id": self.batch_id,
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
        print("FUTU_FACTOR_BATCH_V1|{" + ",".join(parts) + "}")

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
        self.emit_batch("ERROR", {
            "record": "ERROR",
            "session_date_et": day_et,
            "trigger_et": trigger_et,
            "code": code,
            "detail": detail,
            "edge_claim": "PROHIBITED"
        })

    def is_early_close_day(self, day_number):
        return day_number in self.early_close_days or day_number in self.warmup_early_close_days

    def signal_end_for_day(self, day_number):
        if day_number in self.early_close_days:
            return self.early_close_signal_end_minute_et
        return self.signal_end_minute_et

    def summary_minute_for_day(self, day_number):
        if day_number in self.early_close_days:
            return self.early_close_summary_minute_et
        return self.summary_minute_et

    def market_close_for_day(self, day_number):
        if self.is_early_close_day(day_number):
            return self.early_close_market_close_minute_et
        return self.market_close_minute_et

    def expected_events_for_day(self, day_number):
        signal_end = self.signal_end_for_day(day_number)
        return (signal_end - self.signal_start_minute_et) // 5 + 1

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
        self.day_signal_count = 0
        self.day_event_count = 0
        self.day_invalid_f006_count = 0
        self.day_error_count = 0

    def update_recursive_ema(self, close_value, day_number):
        alpha = 2.0 / 21.0
        if self.long_ema20 is None:
            self.long_ema20 = close_value
        else:
            self.long_ema20 = alpha * close_value + (1.0 - alpha) * self.long_ema20
        self.long_bar_count += 1
        self.long_ema_history.append(self.long_ema20)
        if len(self.long_ema_history) > 4:
            self.long_ema_history.pop(0)

        if day_number >= self.sensitivity_start:
            if self.short_ema20 is None:
                self.short_ema20 = close_value
            else:
                self.short_ema20 = alpha * close_value + (1.0 - alpha) * self.short_ema20
            self.short_bar_count += 1
            self.short_ema_history.append(self.short_ema20)
            if len(self.short_ema_history) > 4:
                self.short_ema_history.pop(0)

        self.warmup_close_history.append(close_value)
        if len(self.warmup_close_history) > 2:
            self.warmup_close_history.pop(0)

    def read_measurements(self):
        close_0 = self.positive_number(bar_close(
            symbol=self.trig_symbol_1,
            bar_type=BarType.K_5M,
            select=2,
            session_type=THType.RTH
        ))
        close_1 = self.positive_number(bar_close(
            symbol=self.trig_symbol_1,
            bar_type=BarType.K_5M,
            select=3,
            session_type=THType.RTH
        ))
        close_2 = self.positive_number(bar_close(
            symbol=self.trig_symbol_1,
            bar_type=BarType.K_5M,
            select=4,
            session_type=THType.RTH
        ))
        open_0 = self.positive_number(bar_open(
            symbol=self.trig_symbol_1,
            bar_type=BarType.K_5M,
            select=2,
            session_type=THType.RTH
        ))
        high_0 = self.positive_number(bar_high(
            symbol=self.trig_symbol_1,
            bar_type=BarType.K_5M,
            select=2,
            session_type=THType.RTH
        ))
        low_0 = self.positive_number(bar_low(
            symbol=self.trig_symbol_1,
            bar_type=BarType.K_5M,
            select=2,
            session_type=THType.RTH
        ))
        ema20_0 = self.positive_number(ema(
            symbol=self.trig_symbol_1,
            period=20,
            data_type=DataType.CLOSE,
            bar_type=BarType.K_5M,
            select=2,
            session_type=THType.RTH
        ))
        ema20_1 = self.positive_number(ema(
            symbol=self.trig_symbol_1,
            period=20,
            data_type=DataType.CLOSE,
            bar_type=BarType.K_5M,
            select=3,
            session_type=THType.RTH
        ))
        ema20_3 = self.positive_number(ema(
            symbol=self.trig_symbol_1,
            period=20,
            data_type=DataType.CLOSE,
            bar_type=BarType.K_5M,
            select=5,
            session_type=THType.RTH
        ))
        prior_high = 0.0
        for select_value in (3, 4, 5, 6, 7):
            value = self.positive_number(bar_high(
                symbol=self.trig_symbol_1,
                bar_type=BarType.K_5M,
                select=select_value,
                session_type=THType.RTH
            ))
            if value > prior_high:
                prior_high = value
        body_ratio = None
        if high_0 > low_0:
            body_ratio = (close_0 - open_0) / (high_0 - low_0)
        return {
            "close_0": close_0,
            "close_1": close_1,
            "close_2": close_2,
            "open_0": open_0,
            "high_0": high_0,
            "low_0": low_0,
            "ema20_0": ema20_0,
            "ema20_1": ema20_1,
            "ema20_3": ema20_3,
            "prior_5_high": prior_high,
            "body_ratio": body_ratio
        }

    def audit_states(self, values, platform_states):
        if len(self.long_ema_history) < 4 or len(self.short_ema_history) < 4:
            raise ValueError("WARMUP_HISTORY_TOO_SHORT")
        long_states = {
            "f001": "PASS" if values["close_0"] > self.long_ema_history[-1] else "FAIL",
            "f002": "PASS" if self.long_ema_history[-1] > self.long_ema_history[-4] else "FAIL",
            "f003": (
                "PASS"
                if values["close_1"] <= self.long_ema_history[-2]
                and values["close_0"] > self.long_ema_history[-1]
                else "FAIL"
            )
        }
        short_states = {
            "f001": "PASS" if values["close_0"] > self.short_ema_history[-1] else "FAIL",
            "f002": "PASS" if self.short_ema_history[-1] > self.short_ema_history[-4] else "FAIL",
            "f003": (
                "PASS"
                if values["close_1"] <= self.short_ema_history[-2]
                and values["close_0"] > self.short_ema_history[-1]
                else "FAIL"
            )
        }
        for key in ("f001", "f002", "f003"):
            if platform_states[key] != long_states[key]:
                self.platform_long_mismatches[key] += 1
            if long_states[key] != short_states[key]:
                self.long_short_mismatches[key] += 1
        return long_states, short_states

    def emit_warmup_audit(self, values, long_states, short_states, trigger_et, trigger_utc):
        complete = (
            self.first_observation_et.startswith("2025-07-01T09:35")
            and self.pre_study_long_bar_count == self.expected_warmup_bar_count
            and self.short_bar_count >= 1638
        )
        self.warmup_audit_status = "COMPLETE" if complete else "INCOMPLETE"
        self.emit_batch("WARMUP_AUDIT", {
            "record": "WARMUP_AUDIT",
            "status": self.warmup_audit_status,
            "system_start_target_et": "2025-07-01",
            "first_observation_et": self.first_observation_et,
            "study_start_et": "2025-10-01",
            "sensitivity_start_et": "2025-09-02",
            "warmup_bars_before_train": self.pre_study_long_bar_count,
            "expected_warmup_bars": self.expected_warmup_bar_count,
            "sensitivity_bars_including_first_train_bar": self.short_bar_count,
            "platform_ema20": self.number_text(values["ema20_0"]),
            "system_start_ema20": self.number_text(self.long_ema_history[-1]),
            "sensitivity_start_ema20": self.number_text(self.short_ema_history[-1]),
            "platform_minus_system_start": self.number_text(
                values["ema20_0"] - self.long_ema_history[-1]
            ),
            "system_minus_sensitivity_start": self.number_text(
                self.long_ema_history[-1] - self.short_ema_history[-1]
            ),
            "f001_system_state": long_states["f001"],
            "f002_system_state": long_states["f002"],
            "f003_system_state": long_states["f003"],
            "f001_sensitivity_state": short_states["f001"],
            "f002_sensitivity_state": short_states["f002"],
            "f003_sensitivity_state": short_states["f003"],
            "asof_et": trigger_et,
            "asof_utc": trigger_utc,
            "edge_claim": "PROHIBITED"
        })
        self.warmup_audit_emitted = True
        if not complete:
            self.emit_error(
                self.current_day_et,
                trigger_et,
                "WARMUP_INCOMPLETE",
                str(self.pre_study_long_bar_count)
            )

    def record_signal(self, day_number, minute_et, trigger_et, trigger_utc):
        try:
            values = self.read_measurements()
        except Exception as exc:
            self.emit_error(
                self.current_day_et,
                trigger_et,
                "FACTOR_INPUT_READ_FAILED",
                type(exc).__name__
            )
            return
        close_0 = values["close_0"]
        platform_states = {
            "f001": "PASS" if close_0 > values["ema20_0"] else "FAIL",
            "f002": "PASS" if values["ema20_0"] > values["ema20_3"] else "FAIL",
            "f003": (
                "PASS"
                if values["close_1"] <= values["ema20_1"] and close_0 > values["ema20_0"]
                else "FAIL"
            )
        }
        try:
            long_states, short_states = self.audit_states(values, platform_states)
        except Exception as exc:
            self.emit_error(
                self.current_day_et,
                trigger_et,
                "WARMUP_AUDIT_FAILED",
                type(exc).__name__
            )
            return
        if not self.warmup_audit_emitted:
            self.emit_warmup_audit(values, long_states, short_states, trigger_et, trigger_utc)

        f006_state = "INVALID"
        if values["body_ratio"] is not None:
            f006_state = (
                "PASS"
                if close_0 > values["open_0"] and values["body_ratio"] > 0.60
                else "FAIL"
            )
        else:
            self.day_invalid_f006_count += 1
        clock_hhmm = (minute_et // 60) * 100 + minute_et % 60
        event_id = self.current_day_et.replace("-", "") + "_" + ("%04d" % clock_hhmm)
        item = {
            "event_id": event_id,
            "day_number": day_number,
            "session_date_et": self.current_day_et,
            "signal_et": trigger_et,
            "signal_utc": trigger_utc,
            "signal_minute_et": minute_et,
            "signal_close": close_0,
            "f001_state": platform_states["f001"],
            "f002_state": platform_states["f002"],
            "f003_state": platform_states["f003"],
            "f004_state": "PASS" if close_0 > values["prior_5_high"] else "FAIL",
            "f005_state": (
                "PASS"
                if values["close_2"] < values["close_1"] and values["close_1"] < close_0
                else "FAIL"
            ),
            "f006_state": f006_state,
            "f001_value": close_0 - values["ema20_0"],
            "f002_value": values["ema20_0"] - values["ema20_3"],
            "f003_value": close_0 - values["ema20_0"],
            "f004_value": close_0 - values["prior_5_high"],
            "f005_value": close_0 - values["close_2"],
            "f006_value": values["body_ratio"],
            "ema20_platform_0": values["ema20_0"],
            "ema20_platform_1": values["ema20_1"],
            "ema20_platform_3": values["ema20_3"],
            "ema20_system_start_0": self.long_ema_history[-1],
            "ema20_sensitivity_start_0": self.short_ema_history[-1],
            "close_1": values["close_1"],
            "f001_system_state": long_states["f001"],
            "f002_system_state": long_states["f002"],
            "f003_system_state": long_states["f003"],
            "f001_sensitivity_state": short_states["f001"],
            "f002_sensitivity_state": short_states["f002"],
            "f003_sensitivity_state": short_states["f003"],
            "r3": None,
            "r6": None,
            "r12": None,
            "target_3_et": None,
            "target_3_utc": None,
            "target_3_close": None,
            "target_6_et": None,
            "target_6_utc": None,
            "target_6_close": None,
            "target_12_et": None,
            "target_12_utc": None,
            "target_12_close": None
        }
        self.pending.append(item)
        self.day_signal_count += 1
        self.total_signal_count += 1

    def emit_completed_event(self, item):
        fields = {
            "record": "FACTOR_EVENT",
            "signal_id": item["event_id"],
            "event_id": item["event_id"],
            "session_date_et": item["session_date_et"],
            "signal_time_et": item["signal_et"],
            "signal_time_utc": item["signal_utc"],
            "signal_close": self.number_text(item["signal_close"]),
            "factor_ids": self.factor_ids,
            "definition_hash": self.definition_hash,
            "horizons_bars": "3,6,12",
            "price_use": "NON_EXECUTABLE_CLOSE_TO_CLOSE",
            "overlap_warning": True,
            "independent_samples": False,
            "edge_claim": "PROHIBITED"
        }
        for factor_number in (1, 2, 3, 4, 5, 6):
            key = "f%03d" % factor_number
            fields[key + "_state"] = item[key + "_state"]
            value = item[key + "_value"]
            fields[key + "_value"] = None if value is None else self.number_text(value)
        for key in (
            "ema20_platform_0", "ema20_platform_1", "ema20_platform_3",
            "ema20_system_start_0", "ema20_sensitivity_start_0", "close_1"
        ):
            fields[key] = self.number_text(item[key])
        for factor_number in (1, 2, 3):
            key = "f%03d" % factor_number
            fields[key + "_system_state"] = item[key + "_system_state"]
            fields[key + "_sensitivity_state"] = item[key + "_sensitivity_state"]
        for horizon in (3, 6, 12):
            suffix = str(horizon)
            fields["r" + suffix] = self.number_text(item["r" + suffix])
            fields["target_" + suffix + "_et"] = item["target_" + suffix + "_et"]
            fields["target_" + suffix + "_utc"] = item["target_" + suffix + "_utc"]
            fields["target_" + suffix + "_close"] = self.number_text(
                item["target_" + suffix + "_close"]
            )
        self.emit_batch("FACTOR_EVENT", fields)
        self.day_event_count += 1
        self.total_event_count += 1

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
                continue
            age_bars = (minute_et - item["signal_minute_et"]) // 5
            if age_bars in (3, 6, 12):
                suffix = str(age_bars)
                item["r" + suffix] = close_value / item["signal_close"] - 1.0
                item["target_" + suffix + "_et"] = trigger_et
                item["target_" + suffix + "_utc"] = trigger_utc
                item["target_" + suffix + "_close"] = close_value
            if age_bars == 12:
                if item["r3"] is None or item["r6"] is None:
                    self.emit_error(
                        self.current_day_et,
                        trigger_et,
                        "MISSING_INTERMEDIATE_LABEL",
                        item["event_id"]
                    )
                else:
                    self.emit_completed_event(item)
            elif age_bars > 12:
                self.emit_error(
                    self.current_day_et,
                    trigger_et,
                    "MISSED_EVENT_MATURITY",
                    item["event_id"]
                )
            else:
                remaining.append(item)
        self.pending = remaining

    def emit_day_end(self, trigger_et, trigger_utc):
        expected_events = self.expected_events_for_day(self.current_day_number)
        complete = (
            self.day_signal_count == expected_events
            and self.day_event_count == expected_events
            and len(self.pending) == 0
            and self.day_error_count == 0
        )
        if complete:
            self.completed_day_count += 1
        else:
            self.incomplete_day_count += 1
        self.emit_batch("DAY_END", {
            "record": "DAY_END",
            "session_date_et": self.current_day_et,
            "asof_et": trigger_et,
            "asof_utc": trigger_utc,
            "status": "COMPLETE" if complete else "INCOMPLETE",
            "signal_count": self.day_signal_count,
            "factor_event_count": self.day_event_count,
            "invalid_f006_count": self.day_invalid_f006_count,
            "pending_count": len(self.pending),
            "error_count": self.day_error_count,
            "expected_events": expected_events,
            "edge_claim": "PROHIBITED"
        })
        if self.current_day_number == self.study_end:
            run_complete = (
                self.completed_day_count == self.expected_session_count
                and self.incomplete_day_count == 0
                and self.total_signal_count == self.expected_factor_event_count
                and self.total_event_count == self.expected_factor_event_count
                and self.total_error_count == 0
                and self.warmup_audit_status == "COMPLETE"
            )
            self.emit_batch("RUN_END", {
                "record": "RUN_END",
                "end_time_et": trigger_et,
                "end_time_utc": trigger_utc,
                "status": "COMPLETE" if run_complete else "INCOMPLETE",
                "completed_days": self.completed_day_count,
                "expected_sessions": self.expected_session_count,
                "incomplete_days": self.incomplete_day_count,
                "signal_count": self.total_signal_count,
                "factor_event_count": self.total_event_count,
                "expected_factor_events": self.expected_factor_event_count,
                "label_count": self.total_event_count * 3,
                "expected_labels": self.expected_label_count,
                "error_count": self.total_error_count,
                "warmup_audit_status": self.warmup_audit_status,
                "f001_platform_system_mismatches": self.platform_long_mismatches["f001"],
                "f002_platform_system_mismatches": self.platform_long_mismatches["f002"],
                "f003_platform_system_mismatches": self.platform_long_mismatches["f003"],
                "f001_system_sensitivity_mismatches": self.long_short_mismatches["f001"],
                "f002_system_sensitivity_mismatches": self.long_short_mismatches["f002"],
                "f003_system_sensitivity_mismatches": self.long_short_mismatches["f003"],
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
            self.emit_batch("ERROR", {
                "record": "ERROR",
                "session_date_et": "UNKNOWN",
                "trigger_et": "UNKNOWN",
                "code": "CLOCK_READ_FAILED",
                "detail": type(exc).__name__,
                "edge_claim": "PROHIBITED"
            })
            return

        if day_number < self.system_start_target or day_number > self.study_end:
            return
        if minute_et < self.signal_start_minute_et or minute_et > self.market_close_for_day(day_number):
            return
        if minute_et % 5 != 0:
            return
        trigger_key = str(day_number) + "_" + str(minute_et)
        if trigger_key == self.last_trigger_key:
            return
        self.last_trigger_key = trigger_key

        try:
            symbol_code = get_symbol_code(symbol=self.trig_symbol_1)
            if symbol_code != "US.SPY":
                raise ValueError("SYMBOL_NOT_SPY")
            close_value = self.positive_number(bar_close(
                symbol=self.trig_symbol_1,
                bar_type=BarType.K_5M,
                select=2,
                session_type=THType.RTH
            ))
        except Exception as exc:
            if day_number >= self.study_start:
                self.emit_error(day_et, trigger_et, "BAR_READ_FAILED", type(exc).__name__)
            return

        if self.first_observation_et == "":
            self.first_observation_et = trigger_et
        if day_number == self.study_start and self.pre_study_long_bar_count is None:
            self.pre_study_long_bar_count = self.long_bar_count
        self.update_recursive_ema(close_value, day_number)

        if day_number < self.study_start:
            return
        if day_number != self.current_day_number:
            self.begin_day(day_number, day_et, trigger_et)

        self.resolve_pending(day_number, minute_et, close_value, trigger_et, trigger_utc)
        if self.signal_start_minute_et <= minute_et <= self.signal_end_for_day(day_number):
            self.record_signal(day_number, minute_et, trigger_et, trigger_utc)
        if minute_et == self.summary_minute_for_day(day_number):
            self.emit_day_end(trigger_et, trigger_utc)
