class Strategy(StrategyBase):

    def initialize(self):
        declare_strategy_type(AlgoStrategyType.SECURITY)
        self.trigger_symbols()
        self.custom_indicator()
        self.global_variables()
        self.emit("RUN_START", {
            "study_partition": "TRAIN",
            "system_start_et": "2025-07-01",
            "study_start_et": "2025-10-01",
            "study_end_et": "2026-06-30",
            "expected_sessions": 187,
            "early_close_dates_et": "2025-07-03,2025-11-28,2025-12-24",
            "candidate_ids": "F007,F008,F009,F010,F011,F012",
            "strategy_ids": "S01,S02,S03",
            "definition_hash": self.definition_hash,
            "parameter_attempt": 3,
            "entry_rule": "NEXT_5M_BAR_OPEN_RECONSTRUCTED_AT_BAR_END",
            "entry_time_contract": "SIGNAL_BAR_END_EQUALS_ENTRY_BAR_START;OBSERVED_AT_ENTRY_BAR_END",
            "final_bar_contract": "NEXT_SESSION_SELECT3_BY_EXPLICIT_BAR_ID",
            "adjustment_contract": "LOCKED_OPEND_REHAB_V1",
            "cost_bps_per_side": 2.0,
            "cost_sensitivity_bps_per_side": "1,3",
            "orders_enabled": False,
            "volume_enabled": False,
            "fixture": False,
            "edge_claim": "PROHIBITED"
        })
        self.emit_test_registry()

    def trigger_symbols(self):
        self.trig_symbol_1 = declare_trig_symbol()

    def custom_indicator(self):
        pass

    def global_variables(self):
        self.setup()

    def setup(self):
        self.batch_id = "SPY_C1_STRATEGY_TRAIN_20251001_20260630_V3_1_1"
        self.run_id = self.batch_id
        self.strategy_version = "FUTU_C1_STRATEGY_BATCH_TRAIN_V3_1_1"
        self.strategy_hash = "7b10dc0ad6e47d33372f6a473d9f3bba1884830a149504bd61c0f2ee0ff204ed"
        self.parameter_version = "C1-STRATEGY-FIRST-TRAIN-V3.1.1"
        self.definition_hash = "0c73ae4ef39fda9aa472d59d2cf53cfebf7872595618319fb55bb557f4e4d562"
        self.system_start = 20250701
        self.study_start = 20251001
        self.study_end = 20260630
        self.early_close_days = {20250703: True, 20251128: True, 20251224: True}
        self.rehab_adjustments = {
            20250919: (0.99723, 0.0),
            20251219: (0.99705, 0.0),
            20260320: (0.99727, 0.0),
            20260618: (0.99743, 0.0)
        }
        self.last_trigger_key = ""
        self.current_day = 0
        self.current_day_text = ""
        self.bars = []
        self.day_bars = []
        self.daily = []
        self.clock_atr = {}
        self.ema20 = None
        self.ema50 = None
        self.ema20_history = []
        self.pending_labels = []
        self.pending_entries = []
        self.active_trades = []
        self.cooldown = {}
        self.f008_armed = {"LONG": True, "SHORT": True}
        self.day_signals = 0
        self.day_trades = 0
        self.day_strategy_signals = 0
        self.day_rejected_entries = 0
        self.day_errors = 0
        self.total_signals = 0
        self.total_trades = 0
        self.total_strategy_signals = 0
        self.total_rejected_entries = 0
        self.total_errors = 0
        self.completed_days = 0
        self.day_preopen_regime = "UNKNOWN"
        self.day_prior_context = "UNKNOWN|UNKNOWN|UNKNOWN"
        self.final_bars_injected = 0
        self.basis_adjustments_applied = 0

    def json_value(self, value):
        if value is True:
            return "true"
        if value is False:
            return "false"
        if value is None:
            return "null"
        if isinstance(value, (int, float)):
            return str(value)
        text = str(value).replace("\\", "\\\\").replace("\"", "\\\"")
        return "\"" + text.replace("\r", "\\r").replace("\n", "\\n") + "\""

    def emit(self, event_type, fields):
        payload = {
            "contract_version": "3.1.1",
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
        print("FUTU_FACTOR_STRATEGY_V3_1_1|{" + ",".join(parts) + "}")

    def emit_test_registry(self):
        tests = [
            ("CANDIDATE_SCREEN", "CANDIDATE", 30, "MAX_T_PLUS_HOLM"),
            ("STRATEGY_BASELINE", "L1", 6, "MAX_T_PLUS_HOLM"),
            ("REGIME_INCREMENT", "L2_REGIME", 12, "MAX_T_PLUS_HOLM"),
            ("TIME_INCREMENT", "L2_TIME", 24, "MAX_T_PLUS_HOLM"),
            ("REGIME_TIME_INTERACTION", "L3", 6, "MAX_T_PLUS_HOLM"),
            ("F001_F006_FILTER_INCREMENT", "L4", 36, "MAX_T_PLUS_HOLM")
        ]
        for family, layer, size, adjustment in tests:
            self.emit("TEST_REGISTRY", {
                "test_id": family,
                "family": family,
                "layer": layer,
                "family_size": size,
                "adjustment": adjustment,
                "cluster_unit": "TRADING_DAY",
                "registered_before_train": True
            })

    def text_time(self, value):
        return "%04d-%02d-%02dT%02d:%02d:%02d" % (
            value.year, value.month, value.day, value.hour, value.minute, value.second
        )

    def minute_time(self, day_text, minute, suffix=""):
        return "%sT%02d:%02d:00%s" % (day_text, minute // 60, minute % 60, suffix)

    def scale_price_state(self, factor_a, factor_b):
        if factor_a <= 0:
            raise ValueError("INVALID_REHAB_FACTOR")
        if self.ema20 is not None:
            self.ema20 = factor_a * self.ema20 + factor_b
        if self.ema50 is not None:
            self.ema50 = factor_a * self.ema50 + factor_b
        self.ema20_history = [factor_a * value + factor_b for value in self.ema20_history]
        seen = {}
        for collection in (self.bars, self.day_bars):
            for bar in collection:
                key = id(bar)
                if key in seen:
                    continue
                seen[key] = True
                for field in ("open", "high", "low", "close"):
                    bar[field] = factor_a * bar[field] + factor_b
                if "tr" in bar:
                    bar["tr"] = factor_a * bar["tr"]
        for item in self.daily:
            for field in ("open", "high", "low", "close"):
                item[field] = factor_a * item[field] + factor_b
        for key in self.clock_atr:
            self.clock_atr[key] = [factor_a * value for value in self.clock_atr[key]]
        self.basis_adjustments_applied += 1

    def reject_entry(self, item, reason, asof_et, asof_utc, entry_price=None):
        fields = dict(item)
        fields.update({
            "decision_time_et": asof_et,
            "decision_time_utc": asof_utc,
            "reason": reason,
            "entry_price": entry_price
        })
        self.emit("ENTRY_REJECTED", fields)
        self.day_rejected_entries += 1
        self.total_rejected_entries += 1

    def positive(self, value):
        number = float(value)
        if number <= 0 or number != number:
            raise ValueError("INVALID_PRICE")
        return number

    def read_bar(self, select_value):
        return {
            "open": self.positive(bar_open(symbol=self.trig_symbol_1, bar_type=BarType.K_5M, select=select_value, session_type=THType.RTH)),
            "high": self.positive(bar_high(symbol=self.trig_symbol_1, bar_type=BarType.K_5M, select=select_value, session_type=THType.RTH)),
            "low": self.positive(bar_low(symbol=self.trig_symbol_1, bar_type=BarType.K_5M, select=select_value, session_type=THType.RTH)),
            "close": self.positive(bar_close(symbol=self.trig_symbol_1, bar_type=BarType.K_5M, select=select_value, session_type=THType.RTH))
        }

    def safe_abs(self, value):
        return -value if value < 0 else value

    def safe_high(self, values):
        if len(values) == 0:
            raise ValueError("EMPTY_HIGH_INPUT")
        result = values[0]
        for value in values[1:]:
            if value > result:
                result = value
        return result

    def safe_low(self, values):
        if len(values) == 0:
            raise ValueError("EMPTY_LOW_INPUT")
        result = values[0]
        for value in values[1:]:
            if value < result:
                result = value
        return result

    def safe_total(self, values):
        result = 0.0
        for value in values:
            result += value
        return result

    def update_indicators(self, bar):
        previous_close = self.bars[-1]["close"] if self.bars else bar["close"]
        bar["tr"] = self.safe_high([
            bar["high"] - bar["low"],
            self.safe_abs(bar["high"] - previous_close),
            self.safe_abs(bar["low"] - previous_close)
        ])
        self.ema20 = bar["close"] if self.ema20 is None else (2.0 / 21.0) * bar["close"] + (19.0 / 21.0) * self.ema20
        self.ema50 = bar["close"] if self.ema50 is None else (2.0 / 51.0) * bar["close"] + (49.0 / 51.0) * self.ema50
        self.ema20_history.append(self.ema20)
        if len(self.ema20_history) > 4:
            self.ema20_history.pop(0)
        self.bars.append(bar)
        if len(self.bars) > 300:
            self.bars.pop(0)

    def median(self, values):
        ordered = []
        for value in values:
            inserted = False
            for index in range(len(ordered)):
                if value < ordered[index]:
                    ordered.insert(index, value)
                    inserted = True
                    break
            if not inserted:
                ordered.append(value)
        count = len(ordered)
        if count == 0:
            return None
        middle = count // 2
        return ordered[middle] if count % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0

    def atr(self, length):
        if len(self.bars) < length:
            return None
        return self.safe_total([item["tr"] for item in self.bars[-length:]]) / float(length)

    def time_bucket(self, minute):
        if 575 <= minute < 630:
            return "09:35-10:30"
        if 630 <= minute < 720:
            return "10:30-12:00"
        if 720 <= minute < 840:
            return "12:00-14:00"
        if 840 <= minute <= 955:
            return "14:00-15:55"
        return "OUTSIDE"

    def latest_signal_minute(self, strategy_id, day_number):
        half = day_number in self.early_close_days
        if strategy_id == "S02":
            return 710 if half else 890
        return 740 if half else 920

    def preopen_regime(self):
        if not self.daily or self.ema20 is None or self.ema50 is None:
            return "UNKNOWN"
        if self.daily[-1]["close"] > self.ema20 > self.ema50:
            return "BULL"
        if self.daily[-1]["close"] < self.ema20 < self.ema50:
            return "BEAR"
        return "NEUTRAL"

    def prior_day_context(self):
        if not self.daily:
            return "UNKNOWN|UNKNOWN|UNKNOWN"
        prior = self.daily[-1]
        ranges = [item["high"] - item["low"] for item in self.daily[-21:-1]]
        reference = self.median(ranges)
        ratio = (prior["high"] - prior["low"]) / reference if reference else None
        vol = "LOW" if ratio is not None and ratio < 0.8 else "HIGH" if ratio is not None and ratio > 1.2 else "NORMAL"
        ret = (prior["close"] - prior["open"]) / prior["open"]
        direction = "UP" if ret >= 0.005 else "DOWN" if ret <= -0.005 else "FLAT"
        width = prior["high"] - prior["low"]
        clv = (prior["close"] - prior["low"]) / width if width > 0 else 0.5
        location = "LOW" if clv < 0.3 else "HIGH" if clv > 0.7 else "MID"
        return vol + "|" + direction + "|" + location

    def dynamic_regime(self, close_value, atr20):
        slope_up = len(self.ema20_history) >= 4 and self.ema20_history[-1] > self.ema20_history[-4]
        slope_down = len(self.ema20_history) >= 4 and self.ema20_history[-1] < self.ema20_history[-4]
        trend = "BULL" if close_value > self.ema20 > self.ema50 and slope_up else "BEAR" if close_value < self.ema20 < self.ema50 and slope_down else "NEUTRAL"
        minute = self.day_bars[-1]["minute"]
        clock_values = self.clock_atr.get(str(minute), [])
        reference = self.median(clock_values[-20:])
        atr12 = self.atr(12)
        ratio = atr12 / reference if atr12 is not None and reference else None
        vol = "LOW" if ratio is not None and ratio < 0.8 else "HIGH" if ratio is not None and ratio > 1.2 else "NORMAL" if ratio is not None else "UNKNOWN"
        day_high = self.safe_high([item["high"] for item in self.day_bars])
        day_low = self.safe_low([item["low"] for item in self.day_bars])
        position = (close_value - day_low) / (day_high - day_low) if day_high > day_low else 0.5
        place = "LOW" if position < 0.25 else "HIGH" if position > 0.75 else "MID"
        gap = None
        if self.daily and self.day_bars:
            gap = self.day_bars[0]["open"] / self.daily[-1]["close"] - 1.0
        gap_regime = "GAP_UP" if gap is not None and gap >= 0.003 else "GAP_DOWN" if gap is not None and gap <= -0.003 else "FLAT" if gap is not None else "UNKNOWN"
        return trend, vol, place, ratio, gap_regime

    def frozen_filters(self, bar):
        if len(self.bars) < 7 or self.ema20 is None:
            return "UNAVAILABLE"
        f001 = bar["close"] > self.ema20
        f002 = len(self.ema20_history) >= 4 and self.ema20_history[-1] > self.ema20_history[-4]
        previous = self.bars[-2]
        prior_high = self.safe_high([item["high"] for item in self.bars[-6:-1]])
        f003 = previous["close"] <= self.ema20_history[-2] and bar["close"] > self.ema20
        f004 = bar["close"] > prior_high
        f005 = self.bars[-3]["close"] < previous["close"] < bar["close"]
        width = bar["high"] - bar["low"]
        f006 = width > 0 and bar["close"] > bar["open"] and (bar["close"] - bar["open"]) / width > 0.60
        return "".join("1" if item else "0" for item in (f001, f002, f003, f004, f005, f006))

    def queue_candidate(self, candidate_id, direction, minute, close_value, trigger_et, trigger_utc, regimes):
        signal_id = "%s_%s_%s_%s" % (self.current_day_text.replace("-", ""), str(minute), candidate_id, direction)
        item = {
            "signal_id": signal_id, "candidate_id": candidate_id, "direction": direction,
            "event_unit": "OPENING_EVENT" if candidate_id in ("F009", "F011") else "FIVE_MINUTE_STATE" if candidate_id == "F012" else "FIVE_MINUTE_EVENT",
            "day_number": self.current_day, "minute": minute, "signal_time_et": trigger_et,
            "signal_time_utc": trigger_utc, "signal_price": close_value,
            "time_bucket": self.time_bucket(minute), "preopen_regime": regimes[0],
            "prior_day_context": regimes[1], "dynamic_regime": regimes[2],
            "vol_regime": regimes[3], "day_position": regimes[4], "gap_regime": regimes[5],
            "r15": None, "r30": None, "r60": None
        }
        self.pending_labels.append(item)
        self.day_signals += 1
        self.total_signals += 1
        return signal_id

    def queue_strategy_signal(self, strategy_id, source_id, direction, minute, close_value, trigger_et, trigger_utc, regimes, filters):
        signal_id = "%s_%s_%s_%s" % (
            self.current_day_text.replace("-", ""), str(minute), strategy_id, direction
        )
        self.emit("STRATEGY_SIGNAL_EVENT", {
            "signal_id": signal_id,
            "strategy_id": strategy_id,
            "source_id": source_id,
            "direction": direction,
            "signal_time_et": trigger_et,
            "signal_time_utc": trigger_utc,
            "signal_price": close_value,
            "time_bucket": self.time_bucket(minute),
            "preopen_regime": regimes[0],
            "prior_day_context": regimes[1],
            "dynamic_regime": regimes[2],
            "vol_regime": regimes[3],
            "day_position": regimes[4],
            "gap_regime": regimes[5],
            "factor_filters": filters
        })
        self.day_strategy_signals += 1
        self.total_strategy_signals += 1
        return signal_id

    def queue_trade(self, strategy_id, signal_id, direction, minute, signal_price, stop, target, max_bars, trigger_et, trigger_utc, regimes, filters):
        if minute > self.latest_signal_minute(strategy_id, self.current_day):
            return False
        for item in self.pending_entries + self.active_trades:
            if item["strategy_id"] == strategy_id:
                self.reject_entry({
                    "trade_id": signal_id.replace(strategy_id, strategy_id + "_BUSY"),
                    "strategy_id": strategy_id,
                    "signal_id": signal_id,
                    "direction": direction,
                    "signal_time_et": trigger_et
                }, "POSITION_BUSY", trigger_et, trigger_utc)
                return False
        self.pending_entries.append({
            "trade_id": signal_id.replace("F0", strategy_id + "_"), "strategy_id": strategy_id,
            "signal_id": signal_id, "direction": direction, "signal_time_et": trigger_et,
            "day_number": self.current_day,
            "signal_minute": minute, "signal_price": signal_price, "stop": stop, "target": target,
            "max_bars": max_bars, "time_bucket": self.time_bucket(minute),
            "preopen_regime": regimes[0], "prior_day_context": regimes[1],
            "dynamic_regime": regimes[2], "vol_regime": regimes[3],
            "day_position": regimes[4], "gap_regime": regimes[5], "factor_filters": filters
        })
        return True

    def activate_entries(self, bar, minute, entry_time_et, entry_time_utc, trigger_et, trigger_utc):
        remaining = []
        for item in self.pending_entries:
            if item["day_number"] != self.current_day:
                continue
            if minute <= item["signal_minute"]:
                remaining.append(item)
                continue
            entry_price = bar["open"]
            sign = 1.0 if item["direction"] == "LONG" else -1.0
            stop_valid = entry_price > item["stop"] if sign > 0 else entry_price < item["stop"]
            target_valid = item["target"] > entry_price if sign > 0 else item["target"] < entry_price
            if not stop_valid:
                self.reject_entry(item, "STOP_CROSSED_BEFORE_ENTRY", trigger_et, trigger_utc, entry_price)
                continue
            if item["strategy_id"] in ("S01", "S02"):
                item["target"] = entry_price + sign * 1.5 * self.safe_abs(entry_price - item["stop"])
                target_valid = True
            if not target_valid:
                self.reject_entry(item, "TARGET_CROSSED_BEFORE_ENTRY", trigger_et, trigger_utc, entry_price)
                continue
            item["entry_time_et"] = entry_time_et
            item["entry_time_utc"] = entry_time_utc
            item["entry_observed_at_et"] = trigger_et
            item["entry_observed_at_utc"] = trigger_utc
            item["entry_bar_end_et"] = trigger_et
            item["entry_price"] = entry_price
            item["initial_risk"] = self.safe_abs(entry_price - item["stop"])
            item["reward_to_risk"] = self.safe_abs(item["target"] - entry_price) / item["initial_risk"]
            item["bars_held"] = 0
            item["mfe"] = 0.0
            item["mae"] = 0.0
            self.active_trades.append(item)
        self.pending_entries = remaining

    def resolve_trades(self, bar, trigger_et, trigger_utc):
        remaining = []
        for item in self.active_trades:
            item["bars_held"] += 1
            sign = 1.0 if item["direction"] == "LONG" else -1.0
            favorable = (bar["high"] - item["entry_price"]) / item["entry_price"] if sign > 0 else (item["entry_price"] - bar["low"]) / item["entry_price"]
            adverse = (item["entry_price"] - bar["low"]) / item["entry_price"] if sign > 0 else (bar["high"] - item["entry_price"]) / item["entry_price"]
            item["mfe"] = favorable if favorable > item["mfe"] else item["mfe"]
            item["mae"] = adverse if adverse > item["mae"] else item["mae"]
            gap_stop = bar["open"] <= item["stop"] if sign > 0 else bar["open"] >= item["stop"]
            stop_hit = bar["low"] <= item["stop"] if sign > 0 else bar["high"] >= item["stop"]
            target_hit = bar["high"] >= item["target"] if sign > 0 else bar["low"] <= item["target"]
            ambiguous = stop_hit and target_hit
            reason = "GAP_STOP" if gap_stop else "STOP" if stop_hit else "TARGET" if target_hit else "TIME" if item["bars_held"] >= item["max_bars"] else None
            if reason is None:
                remaining.append(item)
                continue
            exit_price = bar["open"] if gap_stop else item["stop"] if stop_hit else item["target"] if target_hit else bar["close"]
            gross = sign * (exit_price / item["entry_price"] - 1.0)
            target_first_price = item["target"] if ambiguous else exit_price
            target_first_gross = sign * (target_first_price / item["entry_price"] - 1.0)
            fields = dict(item)
            fields.update({
                "trade_date_et": self.current_day_text, "exit_time_et": trigger_et,
                "exit_time_utc": trigger_utc, "exit_price": exit_price,
                "exit_bar_end_et": trigger_et,
                "exit_time_precision": "BAR_END" if reason == "TIME" else "BAR_INTERVAL",
                "gross_return": gross, "cost_bps_per_side": 2.0,
                "net_return": gross - 0.0004, "net_return_cost_1bp": gross - 0.0002,
                "net_return_cost_3bp": gross - 0.0006, "exit_reason": reason,
                "ambiguous": ambiguous, "primary_path": "STOP_FIRST" if ambiguous else "OBSERVED_SINGLE_HIT",
                "target_first_net_return": target_first_gross - 0.0004
            })
            self.emit("TRADE_EVENT", fields)
            self.day_trades += 1
            self.total_trades += 1
        self.active_trades = remaining

    def resolve_labels(self, minute, close_value, trigger_et, trigger_utc):
        remaining = []
        for item in self.pending_labels:
            if item["day_number"] != self.current_day:
                self.error("CROSS_DAY_LABEL", item["signal_id"], trigger_et)
                continue
            age = (minute - item["minute"]) // 5
            if age in (3, 6, 12):
                item["r" + str(age * 5)] = close_value / item["signal_price"] - 1.0
            if age == 12:
                item["target_time_et"] = trigger_et
                item["target_time_utc"] = trigger_utc
                self.emit("SIGNAL_EVENT", item)
            elif age < 12:
                remaining.append(item)
            else:
                self.error("MISSED_LABEL", item["signal_id"], trigger_et)
        self.pending_labels = remaining

    def detect(self, bar, minute, trigger_et, trigger_utc, allow_labels):
        if len(self.bars) < 55 or len(self.day_bars) < 1:
            return
        atr20 = self.atr(20)
        if atr20 is None or atr20 <= 0:
            return
        preopen = self.day_preopen_regime
        prior_context = self.day_prior_context
        dynamic, vol, place, vol_ratio, gap_regime = self.dynamic_regime(bar["close"], atr20)
        regimes = (preopen, prior_context, dynamic, vol, place, gap_regime)
        filters = self.frozen_filters(bar)
        candidates = []
        if allow_labels:
            self.queue_candidate("F012", vol, minute, bar["close"], trigger_et, trigger_utc, regimes)

        if minute >= 605 and len(self.day_bars) >= 7 and len(self.bars) >= 27:
            box = self.day_bars[-7:-1]
            box_high = self.safe_high([item["high"] for item in box])
            box_low = self.safe_low([item["low"] for item in box])
            prior_ranges = []
            for offset in range(7, 27):
                window = self.bars[-offset - 6:-offset]
                if len(window) == 6:
                    prior_ranges.append(
                        self.safe_high([x["high"] for x in window])
                        - self.safe_low([x["low"] for x in window])
                    )
            contraction_ref = self.median(prior_ranges)
            tr_ref = self.median([item["tr"] for item in self.bars[-21:-1]])
            contraction = contraction_ref and (box_high - box_low) <= 0.60 * contraction_ref
            expansion = tr_ref and bar["tr"] >= 1.50 * tr_ref
            if contraction and expansion and bar["close"] > box_high:
                candidates.append(("F007", "LONG"))
            if contraction and expansion and bar["close"] < box_low:
                candidates.append(("F007", "SHORT"))

        z = (bar["close"] - self.ema20) / atr20
        if self.safe_abs(z) < 1.0:
            self.f008_armed = {"LONG": True, "SHORT": True}
        if minute >= 605 and z <= -2.0 and self.f008_armed["LONG"]:
            candidates.append(("F008", "LONG")); self.f008_armed["LONG"] = False
        if minute >= 605 and z >= 2.0 and self.f008_armed["SHORT"]:
            candidates.append(("F008", "SHORT")); self.f008_armed["SHORT"] = False

        if minute == 575 and self.daily:
            gap = self.day_bars[0]["open"] / self.daily[-1]["close"] - 1.0
            if gap >= 0.004 and bar["close"] < self.day_bars[0]["open"]:
                candidates.append(("F009", "SHORT"))
            if gap <= -0.004 and bar["close"] > self.day_bars[0]["open"]:
                candidates.append(("F009", "LONG"))

        if minute >= 635 and len(self.day_bars) >= 13:
            prior_box = self.day_bars[-13:-1]
            high12 = self.safe_high([item["high"] for item in prior_box])
            low12 = self.safe_low([item["low"] for item in prior_box])
            if bar["high"] >= high12 + 0.10 * atr20 and bar["close"] <= high12:
                candidates.append(("F010", "SHORT"))
            if bar["low"] <= low12 - 0.10 * atr20 and bar["close"] >= low12:
                candidates.append(("F010", "LONG"))

        opening = [item for item in self.day_bars if item["minute"] <= 600]
        if minute >= 605 and len(opening) == 6:
            or_high = self.safe_high([item["high"] for item in opening])
            or_low = self.safe_low([item["low"] for item in opening])
            if not self.cooldown.get("F011") and bar["close"] > or_high + 0.10 * atr20:
                candidates.append(("F011", "LONG")); self.cooldown["F011"] = minute
            if not self.cooldown.get("F011") and bar["close"] < or_low - 0.10 * atr20:
                candidates.append(("F011", "SHORT")); self.cooldown["F011"] = minute

        for candidate_id, direction in candidates:
            last = self.cooldown.get(candidate_id, -999)
            if candidate_id not in ("F009", "F011") and minute - last < 30:
                continue
            self.cooldown[candidate_id] = minute
            if allow_labels:
                self.queue_candidate(candidate_id, direction, minute, bar["close"], trigger_et, trigger_utc, regimes)
            sign = 1.0 if direction == "LONG" else -1.0
            if candidate_id == "F008" and self.safe_abs(self.ema20 - self.ema50) <= 0.50 * atr20:
                stop = bar["low"] - atr20 if sign > 0 else bar["high"] + atr20
                signal_id = self.queue_strategy_signal("S03", "F008", direction, minute, bar["close"], trigger_et, trigger_utc, regimes, filters)
                self.queue_trade("S03", signal_id, direction, minute, bar["close"], stop, self.ema20, 6, trigger_et, trigger_utc, regimes, filters)
            if candidate_id == "F011" and minute <= self.latest_signal_minute("S02", self.current_day):
                width = or_high - or_low
                stop = or_high - 0.5 * width if sign > 0 else or_low + 0.5 * width
                risk = self.safe_abs(bar["close"] - stop)
                target = bar["close"] + sign * 1.5 * risk
                signal_id = self.queue_strategy_signal("S02", "F011", direction, minute, bar["close"], trigger_et, trigger_utc, regimes, filters)
                self.queue_trade("S02", signal_id, direction, minute, bar["close"], stop, target, 12, trigger_et, trigger_utc, regimes, filters)

        pullback_long = dynamic == "BULL" and bar["low"] <= self.ema20 < bar["close"]
        pullback_short = dynamic == "BEAR" and bar["high"] >= self.ema20 > bar["close"]
        for direction, passed in (("LONG", pullback_long), ("SHORT", pullback_short)):
            if not passed:
                continue
            signal_id = self.queue_strategy_signal("S01", "PULLBACK", direction, minute, bar["close"], trigger_et, trigger_utc, regimes, filters)
            sign = 1.0 if direction == "LONG" else -1.0
            stop = bar["low"] - 0.25 * atr20 if sign > 0 else bar["high"] + 0.25 * atr20
            risk = self.safe_abs(bar["close"] - stop)
            self.queue_trade("S01", signal_id, direction, minute, bar["close"], stop, bar["close"] + sign * 1.5 * risk, 6, trigger_et, trigger_utc, regimes, filters)

    def error(self, code, detail, trigger_et):
        self.day_errors += 1; self.total_errors += 1
        self.emit("ERROR", {"session_date_et": self.current_day_text, "asof_et": trigger_et, "code": code, "detail": detail})

    def finish_day(self, trigger_et, trigger_utc):
        complete = not self.pending_labels and not self.pending_entries and not self.active_trades and self.day_errors == 0
        self.emit("DAY_END", {
            "session_date_et": self.current_day_text, "asof_et": trigger_et,
            "asof_utc": trigger_utc, "status": "COMPLETE" if complete else "INCOMPLETE",
            "signal_count": self.day_signals, "trade_count": self.day_trades,
            "strategy_signal_count": self.day_strategy_signals,
            "rejected_entry_count": self.day_rejected_entries,
            "pending_labels": len(self.pending_labels), "pending_entries": len(self.pending_entries),
            "active_trades": len(self.active_trades), "error_count": self.day_errors
        })
        if complete:
            self.completed_days += 1
        if self.current_day == self.study_end:
            status = "COMPLETE" if self.completed_days == 187 and self.total_errors == 0 else "INCOMPLETE"
            self.emit("RUN_END", {
                "status": status, "completed_days": self.completed_days,
                "expected_sessions": 187, "signal_count": self.total_signals,
                "trade_count": self.total_trades, "error_count": self.total_errors,
                "strategy_signal_count": self.total_strategy_signals,
                "rejected_entry_count": self.total_rejected_entries,
                "final_bars_injected": self.final_bars_injected,
                "basis_adjustments_applied": self.basis_adjustments_applied,
                "edge_claim": "PROHIBITED"
            })

    def start_day(self, day_number, day_text, previous_bar):
        if self.day_bars:
            adjustment = self.rehab_adjustments.get(day_number)
            if adjustment is not None:
                self.scale_price_state(adjustment[0], adjustment[1])
            expected_final = 780 if self.current_day in self.early_close_days else 960
            if self.day_bars[-1]["minute"] >= expected_final:
                raise ValueError("FINAL_BAR_IDENTITY_DUPLICATE")
            previous_bar["minute"] = expected_final
            previous_bar["session_date_et"] = self.current_day_text
            self.update_indicators(previous_bar)
            self.day_bars.append(previous_bar)
            self.final_bars_injected += 1
            self.daily.append({
                "day": self.current_day_text, "open": self.day_bars[0]["open"],
                "high": self.safe_high([x["high"] for x in self.day_bars]),
                "low": self.safe_low([x["low"] for x in self.day_bars]),
                "close": self.day_bars[-1]["close"]
            })
            if len(self.daily) > 60:
                self.daily.pop(0)
        self.day_preopen_regime = self.preopen_regime()
        self.day_prior_context = self.prior_day_context()
        self.current_day = day_number
        self.current_day_text = day_text
        self.day_bars = []
        self.cooldown = {}
        self.day_signals = 0; self.day_trades = 0; self.day_errors = 0
        self.day_strategy_signals = 0; self.day_rejected_entries = 0

    def handle_data(self):
        try:
            clock_et = device_time(TimeZone.ET); clock_utc = device_time(TimeZone.UTC)
            day_number = clock_et.year * 10000 + clock_et.month * 100 + clock_et.day
            day_text = "%04d-%02d-%02d" % (clock_et.year, clock_et.month, clock_et.day)
            minute = clock_et.hour * 60 + clock_et.minute
            trigger_et = self.text_time(clock_et); trigger_utc = self.text_time(clock_utc) + "Z"
        except Exception as exc:
            self.emit("ERROR", {"session_date_et": "UNKNOWN", "asof_et": "UNKNOWN", "code": "CLOCK_READ_FAILED", "detail": type(exc).__name__})
            return
        if day_number < self.system_start or day_number > self.study_end or minute < 575:
            return
        summary_minute = 775 if day_number in self.early_close_days else 955
        if minute > summary_minute or minute % 5:
            return
        key = str(day_number) + "_" + str(minute)
        if key == self.last_trigger_key:
            return
        self.last_trigger_key = key
        try:
            if get_symbol_code(symbol=self.trig_symbol_1) != "US.SPY":
                raise ValueError("SYMBOL_NOT_SPY")
            bar = self.read_bar(2)
            previous_bar = self.read_bar(3)
        except Exception as exc:
            if day_number >= self.study_start:
                self.error("BAR_READ_FAILED", type(exc).__name__, trigger_et)
            return
        if day_number != self.current_day:
            try:
                self.start_day(day_number, day_text, previous_bar)
            except Exception as exc:
                if day_number >= self.study_start:
                    self.error("DAY_TRANSITION_FAILED", type(exc).__name__, trigger_et)
                return
        bar["minute"] = minute
        bar["session_date_et"] = day_text
        self.update_indicators(bar)
        self.day_bars.append(bar)
        if day_number < self.study_start:
            atr12 = self.atr(12)
            if atr12 is not None:
                values = self.clock_atr.setdefault(str(minute), [])
                values.append(atr12)
                if len(values) > 20:
                    values.pop(0)
            return
        entry_time_et = self.minute_time(day_text, minute - 5)
        utc_minute = clock_utc.hour * 60 + clock_utc.minute
        entry_time_utc = self.minute_time(trigger_utc[:10], utc_minute - 5, "Z")
        self.activate_entries(
            bar, minute, entry_time_et, entry_time_utc, trigger_et, trigger_utc
        )
        self.resolve_trades(bar, trigger_et, trigger_utc)
        self.resolve_labels(minute, bar["close"], trigger_et, trigger_utc)
        signal_end = 715 if day_number in self.early_close_days else 895
        strategy_end = 740 if day_number in self.early_close_days else 920
        if 575 <= minute <= strategy_end:
            self.detect(
                bar, minute, trigger_et, trigger_utc, minute <= signal_end
            )
        atr12 = self.atr(12)
        if atr12 is not None:
            values = self.clock_atr.setdefault(str(minute), [])
            values.append(atr12)
            if len(values) > 20:
                values.pop(0)
        if minute == summary_minute:
            self.finish_day(trigger_et, trigger_utc)
