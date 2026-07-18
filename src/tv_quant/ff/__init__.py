"""Pure domain contracts and calculations for forward-factor signals."""

from .math import calculate_ff, normalize_iv, rank_candidates, select_tenors
from .models import FFResult, OptionLeg, ScanStatus, TenorPair, make_signal_id

__all__ = [
    "FFResult",
    "OptionLeg",
    "ScanStatus",
    "TenorPair",
    "calculate_ff",
    "make_signal_id",
    "normalize_iv",
    "rank_candidates",
    "select_tenors",
]
