from tv_quant.pattern_finder.flat_base import detect_flat_base
from tv_quant.pattern_finder.fixtures import load_fixture
from tv_quant.pattern_finder.models import ohlcv_frame_from_series
from tv_quant.pattern_finder.review import flat_base_review_input


def test_flat_base_review_input_preserves_detector_result() -> None:
    result = detect_flat_base(ohlcv_frame_from_series(load_fixture("TEST_FLAT")))
    review_input = flat_base_review_input(result)
    selected = result.selected

    assert review_input.computer_result == (
        "YES" if result.pattern_flat_base else "NO"
    )
    assert review_input.detector_version == result.detector_version
    assert review_input.scan_as_of_date == selected.base_end.date()
    assert review_input.review_window_start == selected.base_start.date()
    assert review_input.review_window_end == selected.base_end.date()
    assert review_input.diagnostics == {
        "base_length": selected.base_length,
        "base_depth": selected.base_depth_pct,
        "bottom_tests": selected.bottom_test_count,
        "normalized_slope": selected.normalized_slope,
        "support": selected.support_level,
        "resistance": selected.resistance_level,
    }
