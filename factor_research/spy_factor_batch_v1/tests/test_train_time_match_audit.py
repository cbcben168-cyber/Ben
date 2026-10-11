from factor_research.spy_factor_batch_v1.train_time_match_audit import analyze


def test_time_match_audit_distinguishes_matched_and_unmatched_strata():
    events = []
    states = (("PASS", 0.01), ("FAIL", -0.01), ("PASS", 0.02), ("PASS", 0.03))
    times = ("09:35", "09:40", "10:05", "10:10")
    for index, ((state, value), time_text) in enumerate(zip(states, times)):
        event = {
            "session_date_et": "2026-01-02",
            "signal_time_et": f"2026-01-02T{time_text}:00-05:00",
            "r6": value,
        }
        for number in range(1, 7):
            event[f"f{number:03d}_state"] = state
        events.append(event)
    rows = analyze(events, 30)
    assert len(rows) == 6
    row = rows[0]
    assert row["strata_total"] == 2
    assert row["strata_matched"] == 1
    assert row["strata_coverage"] == 0.5
    assert row["matched_raw_diff_bps"] == 200.0
    assert row["unmatched_all_pass_strata"] == 1
    assert row["unmatched_all_fail_strata"] == 0
