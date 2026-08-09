# Phase 1 Pattern Finder — Detector Definition Spec V1

**Version:** 1.0  
**Date:** 2026-08-09  
**Purpose:** Freeze implementable V1 detector formulas for Flat Base, Rounded Base, Compression, READY, and scan cadence.

---

# 1. Scope

This document is implementation-authoritative for Phase 1 detector math.

Phase 1 goals:
- High recall.
- No Human Score.
- No Rule Score 0–100.
- No Machine Learning.
- No Future Outcome.
- No 5D/10D/20D result calculation.
- No auto trading.

The system may return imperfect candidates. Phase 1 is successful if it finds a broad, inspectable set of plausible target patterns.

---

# 2. Time and data contract

Timeframe:

```text
Daily OHLCV
```

Minimum history required:

```text
250 trading days preferred
120 trading days absolute minimum for pattern scan
```

Scan cadence:

```text
SCAN_INTERVAL_TRADING_DAYS = 5
```

Meaning:

- A full universe scan produces a new logical scan batch only after 5 completed XNYS sessions since the previous successful scheduled batch.
- Manual scans are allowed but must be marked `manual_scan = true`.
- Manual scans do not advance the scheduled scan clock unless explicitly configured later.

Future outcome windows are not implemented in Phase 1.

---

# 3. Tradable universe V1

Initial universe:

```text
US Common Stocks
NYSE
NASDAQ
AMEX
```

Default exclusions:

```text
OTC
Preferred
Warrant
Unit
Known suspended/inactive instruments
```

Default liquidity filters:

```text
Close >= 5 USD
Average Dollar Volume 20D >= 20,000,000 USD
Listing history >= 250 trading days where available
```

ADR/ETF handling:
- Common-stock scan is the default.
- ETF and ADR should be configurable, but disabled by default in Phase 1.

---

# 4. Shared definitions

Let:

```text
C_t = Close
H_t = High
L_t = Low
V_t = Volume
ATR14_t = ATR(14)
```

All calculations for candidate date `T0` must use only data `<= T0`.

No future bars may enter any detector.

---

# 5. Base candidate window search

V1 searches candidate base windows:

```text
MIN_BASE_LENGTH = 25 trading days
MAX_BASE_LENGTH = 90 trading days
```

Preferred search lengths:

```text
[30, 40, 50, 60, 75, 90]
```

For each candidate length `N`:

```text
base_high = max(High over last N days)
base_low  = min(Low over last N days)

base_depth_pct =
(base_high - base_low) / base_low
```

High-recall V1 gate:

```text
base_depth_pct <= 0.18
```

Preferred quality zone:

```text
base_depth_pct <= 0.15
```

The detector may return diagnostics for candidates between 15% and 18% rather than rejecting them from the entire scan.

---

# 6. Bottom location filter

Purpose:
Reduce high-level consolidation false positives without being overly strict.

Define:

```text
range_120_high = max(High, last 120 days)
range_120_low  = min(Low, last 120 days)

range_position_120 =
(Close_T0 - range_120_low)
/
(range_120_high - range_120_low)
```

Default high-recall condition:

```text
range_position_120 <= 0.45
```

This condition is a soft eligibility diagnostic in Phase 1, not a hard rejection if the other pattern structure is strong.

Also calculate:

```text
prior_120_drawdown =
(range_120_high - base_low) / range_120_high
```

Preferred:

```text
prior_120_drawdown >= 0.10
```

Strong:

```text
>= 0.15
```

Again, V1 should store the value rather than hard-reject every candidate below 10%.

---

# 7. Flat Base detector V1

A Flat Base candidate requires:

```text
25 <= base_length <= 90
base_depth_pct <= 0.18
```

## 7.1 Bottom stability

Define local pivot lows using:

```text
PIVOT_LEFT = 2
PIVOT_RIGHT = 2
```

A day is a pivot low if its Low is the minimum within:

```text
[t-2, t+2]
```

For the base window:

```text
bottom_reference = minimum pivot low
```

A pivot low is considered part of the same bottom zone if:

```text
(pivot_low - bottom_reference) / bottom_reference <= 0.04
```

Default:

```text
BOTTOM_TOLERANCE_PCT = 0.04
MIN_BOTTOM_TESTS = 2
```

Preferred quality:

```text
bottom tests >= 3
tolerance <= 0.03
```

Phase 1 hard minimum:

```text
bottom tests >= 2
```

## 7.2 Flatness

Fit linear regression to Close over the base window.

Normalize slope:

```text
normalized_slope =
regression_slope
/
mean(Close over base window)
```

Convert to approximate per-day percentage slope.

Flat Base high-recall gate:

```text
abs(normalized_slope) <= 0.0015
```

Equivalent approximate tolerance:

```text
<= 0.15% of mean price per trading day
```

## 7.3 Flat Base output

Return:

```text
pattern_flat_base = True/False
flat_base_length
flat_base_depth_pct
flat_bottom_test_count
flat_bottom_tolerance_pct
flat_normalized_slope
flat_support_level
flat_resistance_level
```

---

# 8. Rounded Base detector V1

A Rounded Base candidate uses a window:

```text
30 <= base_length <= 90
```

Split into approximately equal thirds:

```text
left
middle
right
```

For each third fit linear regression to Close:

```text
left_slope
middle_slope
right_slope
```

Normalize each slope by mean Close of its segment.

High-recall rounded condition:

```text
left_slope < -0.0003
abs(middle_slope) <= 0.0015
right_slope > 0.0003
```

And slope transition:

```text
left_slope < middle_slope < right_slope
```

## 8.1 Quadratic confirmation

Fit:

```text
Price_t = a*t^2 + b*t + c
```

Normalize `a` by average price where needed for comparability.

V1 confirmation:

```text
a > 0
quadratic_r2 >= 0.35
```

Important:

- Quadratic confirmation is supportive, not sufficient by itself.
- Rounded Base can pass with valid slope transition even if `R² < 0.35`, but must then be flagged `rounded_low_confidence = true`.

## 8.2 Right-side recovery

Calculate pivot lows in right half.

Preferred:

```text
most recent pivot low > previous pivot low
```

Output:

```text
higher_low_recent = True/False
```

Do not require it as a hard gate in Phase 1.

## 8.3 Rounded Base output

Return:

```text
pattern_rounded_base
rounded_base_length
rounded_base_depth_pct
left_slope
middle_slope
right_slope
quadratic_a
quadratic_r2
higher_low_recent
rounded_low_confidence
rounded_support_level
rounded_resistance_level
```

---

# 9. Compression detector V1

Compression is evaluated on the most recent part of a base.

## 9.1 ATR contraction

Define:

```text
atr14 = ATR(14)
atr_reference = mean(ATR14 over prior 60 days)

atr_ratio =
atr14_T0 / atr_reference
```

High-recall compression:

```text
atr_ratio <= 0.90
```

Preferred:

```text
atr_ratio <= 0.80
```

Strong:

```text
atr_ratio <= 0.70
```

## 9.2 Volume dry-up

Define:

```text
avg_vol_20 = mean(Volume, last 20 days)
avg_vol_60 = mean(Volume, last 60 days)

volume_ratio =
avg_vol_20 / avg_vol_60
```

High-recall:

```text
volume_ratio <= 0.90
```

Preferred:

```text
volume_ratio <= 0.80
```

Strong:

```text
volume_ratio <= 0.70
```

## 9.3 Price-range contraction

Define:

```text
range_10_pct =
(max(High, 10D) - min(Low, 10D))
/
mean(Close, 10D)

range_40_pct =
(max(High, 40D) - min(Low, 40D))
/
mean(Close, 40D)

range_contraction_ratio =
range_10_pct / range_40_pct
```

High-recall compression:

```text
range_contraction_ratio <= 0.75
```

## 9.4 Compression V1 boolean

Compression passes if at least two of the three are true:

```text
ATR contraction
Volume dry-up
Price-range contraction
```

Output each component separately.

No score is created.

---

# 10. Resistance definition V1

For a selected base window:

```text
resistance_raw = max(High over base window excluding T0)
```

To reduce one-day spike distortion, also calculate:

```text
upper_quantile = 90th percentile of High over base window excluding T0
```

Default resistance:

```text
if resistance_raw > upper_quantile + 1.5 * ATR14_T0:
    resistance = upper_quantile
    resistance_spike_adjusted = True
else:
    resistance = resistance_raw
    resistance_spike_adjusted = False
```

This is V1 heuristic and must be visible in diagnostics.

---

# 11. Distance to resistance

Define:

```text
distance_to_resistance_pct =
(resistance - Close_T0) / resistance
```

Interpretation:

```text
> 0 = still below resistance
= 0 = at resistance
< 0 = above resistance
```

---

# 12. READY detector V1

READY is not a score.

READY requires:

```text
(pattern_flat_base OR pattern_rounded_base)
AND
compression = True
AND
distance_to_resistance_pct <= 0.03
AND
distance_to_resistance_pct >= -0.005
```

Meaning:

- within 3% below resistance,
- or no more than 0.5% above resistance.

Preferred READY:

```text
distance_to_resistance_pct <= 0.02
```

If more than 0.5% above resistance:

```text
do not classify READY
```

It may later be classified as breakout-like, but Phase 1 does not implement Future Outcome.

---

# 13. Breakout-like diagnostic for visual review

Phase 1 may calculate a current-bar diagnostic only.

This is not an Outcome label.

Define:

```text
close_location =
(Close_T0 - Low_T0)
/
(High_T0 - Low_T0)
```

Define:

```text
rvol_20 =
Volume_T0 / mean(Volume, prior 20 completed days)
```

Current-bar breakout-like:

```text
Close_T0 > resistance + 0.20 * ATR14_T0
AND
rvol_20 >= 1.50
AND
close_location >= 0.70
```

Output:

```text
current_breakout_like = True/False
```

It must never be named:

```text
successful_breakout
future_breakout
outcome
```

---

# 14. Candidate inclusion V1

A symbol may enter Phase 1 candidates if:

```text
data_quality_pass
AND
(
    pattern_flat_base
    OR pattern_rounded_base
    OR ready
    OR current_breakout_like
)
```

Do not require all compression conditions for every base candidate.

Phase 1 is intentionally high recall.

---

# 15. Multiple window handling

A symbol may match multiple base lengths.

Do not create duplicate visible candidates.

For each pattern family select the best diagnostic window using deterministic rules.

Flat Base preferred window order:

1. Higher bottom-test count.
2. Lower base depth.
3. Lower absolute normalized slope.
4. Longer base length.
5. If still tied, shortest encoded window id lexicographically/deterministically.

Rounded Base preferred window order:

1. Valid slope transition.
2. Higher quadratic R².
3. Positive higher-low diagnostic.
4. Lower base depth.
5. Longer base length.

All matched windows may be stored in diagnostics.

---

# 16. Data quality gate

Reject candidate calculation when:

```text
duplicate dates
non-monotonic dates
High < Low
High < max(Open, Close)
Low > min(Open, Close)
missing/non-finite OHLC
Volume < 0
insufficient history
stale beyond latest expected complete XNYS session
symbol mismatch
```

Missing sessions:

- Do not forward-fill.
- Report quality warning.
- If missing sessions occur inside the active detector window, block the candidate.

---

# 17. Chart Review rendering contract

Display:

```text
120–250 daily bars
Candlestick
Volume
Selected base window
Support
Resistance
MA20 optional
```

Diagnostics:

```text
Pattern type
Base length
Base depth
Bottom tests
ATR ratio
Volume ratio
Range contraction ratio
Left/Middle/Right slope
Quadratic R²
Distance to resistance
READY
Current breakout-like
Data quality status
```

Do not display:

```text
Human Score
Rule Score 0–100
Shape Score
Outcome Score
Future 5D/10D/20D
```

---

# 18. Known-positive / near-miss fixtures

Before live-universe acceptance, tests must include synthetic fixtures for:

```text
flat_base_clean
flat_base_too_deep
flat_base_unstable_lows
rounded_base_clean
rounded_base_wrong_slope_order
rounded_base_low_r2_but_valid_slopes
compression_atr_volume
compression_atr_range
compression_only_one_condition
ready_clean
ready_too_far
breakout_like_clean
breakout_like_low_volume
insufficient_history
missing_session_in_window
```

Each fixture must state the expected boolean outputs explicitly.

---

# 19. Phase 1 acceptance target

Phase 1 does not require a profitable backtest.

Acceptance is based on:

```text
Data correctness
Detector determinism
High-recall candidate discovery
Visual inspectability
No future leakage
Stable 5-trading-day scan batch behavior
```

Manual evaluation should include:

```text
at least 100 candidate charts
plus
at least 100 non-candidate random charts
```

The goal is to identify systematic false positives and obvious misses before Phase 2.

---

# 20. Versioning

All numeric values in this document belong to:

```text
PATTERN_DETECTOR_VERSION = "phase1-v1"
```

Any later threshold change must create:

```text
phase1-v2
phase1-v3
...
```

Historical scan batches must preserve the detector version used at T0.

---

## END
