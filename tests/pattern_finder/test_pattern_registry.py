from dataclasses import replace

import pytest

from tv_quant.pattern_finder.pattern_registry import (
    FLAT_BASE_REASON_TAGS,
    enabled_pattern_profiles,
    get_pattern_profile,
)


def test_flat_base_is_the_only_enabled_profile() -> None:
    profile = get_pattern_profile("flat_base")

    assert profile.pattern_type == "flat_base"
    assert profile.display_name_zh == "平底形态"
    assert profile.display_name_en == "Flat Base"
    assert profile.reason_tags == FLAT_BASE_REASON_TAGS
    assert tuple(field.key for field in profile.diagnostic_fields) == (
        "base_length",
        "base_depth",
        "bottom_tests",
        "normalized_slope",
        "support",
        "resistance",
    )
    assert profile.overlay_capabilities == frozenset(
        {"review_window", "support", "resistance"}
    )
    assert tuple(item.pattern_type for item in enabled_pattern_profiles()) == (
        "flat_base",
    )


def test_flat_base_profile_contains_frozen_review_copy() -> None:
    profile = get_pattern_profile("flat_base")

    assert profile.review_question_yes == "这段价格结构是否像一个平底形态？"
    assert profile.review_question_no == "是否存在电脑漏掉的明显平底形态？"
    assert "不要考虑未来涨跌" in profile.review_help


def test_unknown_and_disabled_profiles_are_not_selectable() -> None:
    with pytest.raises(KeyError, match="未注册形态"):
        get_pattern_profile("missing")

    disabled = replace(
        get_pattern_profile("flat_base"),
        pattern_type="test_only",
        enabled=False,
    )
    assert enabled_pattern_profiles({"test_only": disabled}) == ()
