from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class DiagnosticField:
    key: str
    source_column: str
    display_name_zh: str
    format_spec: str | None = None


@dataclass(frozen=True, slots=True)
class PatternProfile:
    pattern_type: str
    display_name_zh: str
    display_name_en: str
    review_question_yes: str
    review_question_no: str
    review_help: str
    reason_tags: tuple[str, ...]
    diagnostic_fields: tuple[DiagnosticField, ...]
    overlay_capabilities: frozenset[str]
    enabled: bool


FLAT_BASE_REASON_TAGS = (
    "底部区间太深",
    "底部持续时间太短",
    "低点区域不集中",
    "横盘稳定性不足",
    "整体仍明显向上",
    "整体仍明显向下",
    "波动区间过宽",
    "阻力区域不清晰",
    "底部测试次数不足",
    "结构不像平底",
    "其他",
)

FLAT_BASE_PROFILE = PatternProfile(
    pattern_type="flat_base",
    display_name_zh="平底形态",
    display_name_en="Flat Base",
    review_question_yes="这段价格结构是否像一个平底形态？",
    review_question_no="是否存在电脑漏掉的明显平底形态？",
    review_help=(
        "只根据当前及之前已经发生的K线判断。"
        "不要考虑未来涨跌、突破是否成功或后续收益。"
    ),
    reason_tags=FLAT_BASE_REASON_TAGS,
    diagnostic_fields=(
        DiagnosticField("base_length", "Base Length", "底部周期", "integer"),
        DiagnosticField("base_depth", "Base Depth", "底部深度", "percent"),
        DiagnosticField("bottom_tests", "Bottom Tests", "底部测试次数", "integer"),
        DiagnosticField(
            "normalized_slope",
            "Normalized Slope",
            "标准化斜率",
            ".8f",
        ),
        DiagnosticField("support", "Support", "支撑位", ".4f"),
        DiagnosticField("resistance", "Resistance", "阻力位", ".4f"),
    ),
    overlay_capabilities=frozenset({"review_window", "support", "resistance"}),
    enabled=True,
)

PATTERN_REGISTRY: Mapping[str, PatternProfile] = MappingProxyType(
    {FLAT_BASE_PROFILE.pattern_type: FLAT_BASE_PROFILE}
)


def get_pattern_profile(
    pattern_type: str,
    *,
    require_enabled: bool = True,
) -> PatternProfile:
    try:
        profile = PATTERN_REGISTRY[pattern_type]
    except KeyError as error:
        raise KeyError(f"未注册形态: {pattern_type}") from error
    if require_enabled and not profile.enabled:
        raise ValueError(f"形态尚未启用: {pattern_type}")
    return profile


def enabled_pattern_profiles(
    registry: Mapping[str, PatternProfile] = PATTERN_REGISTRY,
) -> tuple[PatternProfile, ...]:
    return tuple(profile for profile in registry.values() if profile.enabled)
