# C1 Phase 4 Mechanism Study Pre-registration

Status: `FROZEN_BEFORE_PHASE4_TRAIN_RESULTS`

This module is limited to synthetic verification until a separate Phase 4.2
authorization.  It must not read Phase 4 TRAIN returns, Validation/OOS, account,
position, order, Volume, VWAP, or RVOL data.

## Primary family

- Family: `P4_PRIMARY_V1`
- Family size: 3
- `P4_M01_ALL`: Rolling-Range Rejection
- `P4_M02_ALL`: Compression Expansion
- `P4_M06_ALL`: True Gap Fill Reversal
- M03/M04/M05: `PROPOSED_NOT_EXECUTED`

Long and Short trades are pooled within each primary hypothesis.  Directional
subsets are descriptive only.  The complete three-hypothesis family remains in
Holm and max-|t| adjustment even when a hypothesis has zero or insufficient
samples.

## Authorized data contract

- Symbol: `US.SPY`.
- RTH completed five-minute OHLC only, `America/New_York` bar-end labels.
- Authorized TRAIN dates: 2025-10-01 through 2026-06-30, 187 sessions.
- Price basis: `AS_OF_DYNAMIC_FORWARD_FROM_GET_REHAB` for every price anchor.
- TRAIN-preceding price rows must not enter any Phase 4 feature or warm-up.
- A complete XNYS session grid is a global DATA_GATE requirement.  Missing a
  required future bar blocks the entire run as `DATA_INCOMPLETE`; it cannot
  cancel only the affected trade.

## Volatility contract

The first RTH bar of each session uses `TR = H-L`; overnight gaps never enter
Intraday TR.  Other bars use same-session previous close.  Intraday ATR20 is
the mean of exactly `iloc[g-20:g]`, excluding the signal bar, and may roll
across TRAIN sessions.

DailyTR uses current daily H/L and the preceding authorized TRAIN daily close.
DailyATR20 uses exactly `daily_tr.iloc[k-20:k]`.  Because DailyTR for the first
TRAIN session is unavailable, DailyATR first becomes available on zero-based
session `k=21` (the 22nd TRAIN session).  Unavailable periods are labelled
`WARMUP_UNAVAILABLE` and are never imputed.

## Mechanism summary

### P4_M01_ALL

At same-session position `j`, the reference range is exactly
`day.iloc[j-12:j]`.  A Long breaches the lower boundary by at least 0.10 ATR,
closes back inside and bullish; Short is mirrored.  Stop is the signal extreme
plus/minus 0.25 ATR, target is the frozen range midpoint, and time exit is six
holding bars.

### P4_M02_ALL

At `j>=24`, reference boxes are `j-24:j-18`, `j-18:j-12`, and `j-12:j-6`;
compression box is `j-6:j`; all contain six bars and exclude the signal bar.
The compression width is at most 0.60 times the median reference width.  Signal
TR is at least 1.50 times the median of `day.tr.iloc[j-24:j]`, and close must
break the box by 0.10 ATR.  Stop is beyond the opposite box edge by 0.10 ATR,
target is 1.5R, and time exit is twelve holding bars.

### P4_M06_ALL

The Gap magnitude must be at least 0.50 DailyATR.  Only same-session positions
`j=1..5` (09:40 through 10:00 ET) may signal.  No earlier or current bar may
touch the prior close.  The current close must remain inside the Gap, retrace at
least 25%, cross the preceding same-session bar extreme, and close in the fill
direction.  Stop is the session extreme as of the signal plus/minus 0.10 ATR;
target is the prior RTH close; time exit is twelve holding bars.

## Daily signal and execution contract

The first complete signal consumes that mechanism's daily signal entitlement.
An entry cancellation does not permit a later signal.  Cancellations remain in
the signal audit but do not become zero-return trades.

Entry is the next same-session bar open.  Initial risk and target distance must
be strictly positive.  If `d*(target-entry)/entry <= 0.0004`, cancel as
`NON_POSITIVE_NET_TARGET`.  This is an economic feasibility gate, not a
minimum-R filter.

The planned XNYS close known at signal time determines whether the full holding
window fits.  The implementation must not inspect future OHLC completeness to
select trades.  Stop gaps fill at the bar open; target gaps are conservatively
capped at the target.  When Stop and Target are both touched in a five-minute
bar, `STOP_FIRST` is primary and Target-first is sensitivity only.

## Statistical contract

- Estimand: equally weighted per-trade net return.
- Primary cost: round-trip 4 bp.
- Sensitivity: 2 bp.
- Candidate robustness requirement: mean net return at 6 bp must be `> 0`.
- Resampling: 2,000 complete-day cluster draws over one common 187-day index.
- Seed base: 31,415,926.
- Multiplicity: fixed three-hypothesis Holm plus max-|t| simultaneous interval.
- Minimum: 50 trades and 40 trading days.
- Simultaneous CI lower bound: `> 0`.
- Finite PF: `> 1.10`.
- Positive months: at least 6.
- Largest positive-month share of total positive-month profit: `<= 0.40`.
- Zero/untestable hypotheses remain family members with p=1 and cannot qualify.
- TRAIN output, if separately authorized later, may only be an exploratory
  candidate and never a validated Edge.

## Overlap and stopping

Overlap uses the first complete signal, including later cancellations.  A pair
matches only on the same date and direction with signal positions differing by
at most one bar.  With one signal per mechanism/day matching is one-to-one.
`Jaccard = M/(nA+nB-M)` and `>=0.80` is `HIGH_OVERLAP`.  An empty union is
`OVERLAP_NOT_COMPUTABLE`, not zero.  High overlap blocks the attempt before
profitability is revealed; it never permits deleting a hypothesis from the
registered family.

Any data identity, adjustment basis, lookahead, session completeness, rule
hash, family membership, state-machine, execution, statistics, or write-scope
failure blocks the study.  Every attempt and abandoned version must remain in
the attempt registry.
