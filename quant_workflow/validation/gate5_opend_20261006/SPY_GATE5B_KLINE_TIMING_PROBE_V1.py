class Strategy(StrategyBase):

    def initialize(self):
        declare_strategy_type(AlgoStrategyType.SECURITY)
        self.trigger_symbols()
        self.custom_indicator()
        self.global_variables()
        print("FUTU_GATE5B_TIMING_V1 event=START orders_enabled=False indicators_enabled=False bar_timestamp_api=NOT_AVAILABLE_IN_PROVIDED_MANUAL")

    def trigger_symbols(self):
        self.trig_symbol_1 = declare_trig_symbol()

    def custom_indicator(self):
        pass

    def global_variables(self):
        self.last_probe_minute = -1

    def handle_data(self):
        try:
            clock_et = device_time(TimeZone.ET)
        except Exception as exc:
            print("FUTU_GATE5B_TIMING_V1 clock_et_ERROR=" + type(exc).__name__ + ":" + str(exc)[:160])
            return

        if clock_et.year != 2026 or clock_et.month != 10 or clock_et.day != 6:
            return

        probe_minute = clock_et.hour * 60 + clock_et.minute
        if probe_minute not in (570, 571, 575):
            return
        if probe_minute == self.last_probe_minute:
            return
        self.last_probe_minute = probe_minute

        tag = "FUTU_GATE5B_TIMING_V1 trigger_et=" + repr(clock_et)

        try:
            symbol = get_symbol_code(symbol=self.trig_symbol_1)
            print(tag + " symbol=" + repr(symbol))
        except Exception as exc:
            print(tag + " symbol_ERROR=" + type(exc).__name__ + ":" + str(exc)[:160])

        try:
            clock_utc = device_time(TimeZone.UTC)
            print(tag + " clock_utc=" + repr(clock_utc))
        except Exception as exc:
            print(tag + " clock_utc_ERROR=" + type(exc).__name__ + ":" + str(exc)[:160])
            try:
                clock_gmt = device_time(TimeZone.GMT)
                print(tag + " clock_gmt_fallback=" + repr(clock_gmt))
            except Exception as fallback_exc:
                print(tag + " clock_gmt_fallback_ERROR=" + type(fallback_exc).__name__ + ":" + str(fallback_exc)[:160])

        try:
            o = bar_open(symbol=self.trig_symbol_1, bar_type=BarType.K_1M, select=1, session_type=THType.RTH)
            h = bar_high(symbol=self.trig_symbol_1, bar_type=BarType.K_1M, select=1, session_type=THType.RTH)
            l = bar_low(symbol=self.trig_symbol_1, bar_type=BarType.K_1M, select=1, session_type=THType.RTH)
            c = bar_close(symbol=self.trig_symbol_1, bar_type=BarType.K_1M, select=1, session_type=THType.RTH)
            v = bar_volume(symbol=self.trig_symbol_1, bar_type=BarType.K_1M, select=1, session_type=THType.RTH)
            print(tag + " period=1m select=1 OHLCV=" + repr((o, h, l, c, v)))
        except Exception as exc:
            print(tag + " period=1m select=1 ERROR=" + type(exc).__name__ + ":" + str(exc)[:160])

        try:
            o = bar_open(symbol=self.trig_symbol_1, bar_type=BarType.K_1M, select=2, session_type=THType.RTH)
            h = bar_high(symbol=self.trig_symbol_1, bar_type=BarType.K_1M, select=2, session_type=THType.RTH)
            l = bar_low(symbol=self.trig_symbol_1, bar_type=BarType.K_1M, select=2, session_type=THType.RTH)
            c = bar_close(symbol=self.trig_symbol_1, bar_type=BarType.K_1M, select=2, session_type=THType.RTH)
            v = bar_volume(symbol=self.trig_symbol_1, bar_type=BarType.K_1M, select=2, session_type=THType.RTH)
            print(tag + " period=1m select=2 OHLCV=" + repr((o, h, l, c, v)))
        except Exception as exc:
            print(tag + " period=1m select=2 ERROR=" + type(exc).__name__ + ":" + str(exc)[:160])

        try:
            o = bar_open(symbol=self.trig_symbol_1, bar_type=BarType.K_5M, select=1, session_type=THType.RTH)
            h = bar_high(symbol=self.trig_symbol_1, bar_type=BarType.K_5M, select=1, session_type=THType.RTH)
            l = bar_low(symbol=self.trig_symbol_1, bar_type=BarType.K_5M, select=1, session_type=THType.RTH)
            c = bar_close(symbol=self.trig_symbol_1, bar_type=BarType.K_5M, select=1, session_type=THType.RTH)
            v = bar_volume(symbol=self.trig_symbol_1, bar_type=BarType.K_5M, select=1, session_type=THType.RTH)
            print(tag + " period=5m select=1 OHLCV=" + repr((o, h, l, c, v)))
        except Exception as exc:
            print(tag + " period=5m select=1 ERROR=" + type(exc).__name__ + ":" + str(exc)[:160])

        try:
            o = bar_open(symbol=self.trig_symbol_1, bar_type=BarType.K_5M, select=2, session_type=THType.RTH)
            h = bar_high(symbol=self.trig_symbol_1, bar_type=BarType.K_5M, select=2, session_type=THType.RTH)
            l = bar_low(symbol=self.trig_symbol_1, bar_type=BarType.K_5M, select=2, session_type=THType.RTH)
            c = bar_close(symbol=self.trig_symbol_1, bar_type=BarType.K_5M, select=2, session_type=THType.RTH)
            v = bar_volume(symbol=self.trig_symbol_1, bar_type=BarType.K_5M, select=2, session_type=THType.RTH)
            print(tag + " period=5m select=2 OHLCV=" + repr((o, h, l, c, v)))
        except Exception as exc:
            print(tag + " period=5m select=2 ERROR=" + type(exc).__name__ + ":" + str(exc)[:160])
