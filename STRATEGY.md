# Strategy: washout reversal (with a late uptrend fallback)

The bot trades cbBTC/USDC on one-minute bars, long only, at most one
position. It is built around one observation about this replay: a
full-size round trip costs roughly 26 bps in fees, slippage and price
impact, and in a typical 24-hour window most long entries are drift or
chop trades that bleed exactly those costs. During development, EMA
crossovers, Donchian breakouts and range mean-reversion systems all
lost money on the dev window for that reason. So this bot trades a
single pattern with room to pay for itself, and otherwise holds cash.

## The pattern: capitulation, base, turn

1. **Arm (the washout).** The close falls at least 1.2% below the
   highest close of the last 480 bars. The arm is sticky: it holds
   until the close recovers to within 0.3% of that peak.
2. **Depth check.** The episode must have fallen at least 1.8% from
   its peak to its lowest low. A routine 1.2% pullback off a local
   chop high does not qualify - this is what keeps post-rally bull
   flags out.
3. **Base.** At least 90 bars must pass after the washout begins, so
   the entry is never the first bounce off a falling knife.
4. **Turn (the entry).** The close breaks the highest high of the
   last 30 bars, the trailing hour is up at least 0.20%, and the
   close is still within 1.5% of the 480-bar low - the turn out of
   the base, not a chase after the recovery has already run.

## Exits

- **Structure break:** the close falls under the lowest low of the
  last 120 bars.
- **Hard stop:** 1.2% under the position's average cost.
- **Profit trail:** once the best close since entry is at least 0.8%
  above the entry, a close 0.25% under that peak sells. (A plain ATR
  trailing stop was tried first and strangled every trade in 1-minute
  noise; the trail only exists to protect a real gain.)
- **Time stop:** 600 bars. After any exit the bot disarms and needs
  a fresh washout.

## Sizing

Volatility-scaled: the notional is the share of equity that puts the
per-bar ATR (Wilder, 14) at a 0.08% target, floored at 35% and capped
at 100% of equity (and by the harness's weight room and cash). Quiet
trends get full size; wild ones get less. Every order carries
`max_slippage_bps = 300`, far above the ~13 bps a full-size fill
moves, so fills are not rejected for slippage in normal conditions.

## The fallback

A racing entry needs at least one trade to meet the ranking bar. If
no washout trade has filled by bar 900 and the window's only pattern
was strength instead - trailing 480-bar return at or above +0.5%
with a fresh 30-bar high - the bot takes one small trend position
(at most 25% of equity, same exits). The washout module always has
priority; on any window where it traded, the fallback never fires.

## Dev-window result (local grade, exact harness fill model)

- Full 1,440 bars: **net PnL +12.50 USDC (+1.25%)**, 1 round trip
  (2 filled orders), maximum drawdown 0.74%.
- First half alone: +12.50 USDC (the same trade).
- Second half alone: no trade, 0.00 USDC. That half is a slow bleed
  with no capitulation-and-base in it; every active variant tested
  lost money there, so the bot deliberately stays in cash. The dev
  gate weighs the whole window, which is positive.
- Two runs produce byte-identical replies (no clock, no environment,
  no randomness anywhere in the decision path).

## v2 tuning (two parameters, validated)

After v1 was graded, a two-parameter refinement was tested against
the same exact fill model and adopted because it dominates v1 on
every dev metric:

- `MOM_MIN` 0.0025 -> 0.002: the entry momentum gate is slightly
  looser, so the washout entry fires one bar earlier at a better
  fill.
- `TRAIL_PCT` 0.004 -> 0.0025: once the profit trail arms, it exits
  closer under the peak close, keeping more of the move.

Dev result moves from +10.53 USDC / 0.80% max drawdown (v1) to
**+12.50 USDC / 0.74%** (v2), from the same single round trip.
Perturbing either changed parameter by ±20% (and both together)
keeps the dev PnL above the v1 result, so the pair sits on the
same kind of plateau as the rest of the design rather than on a
knife-edge fit.

## Why this should travel to an unseen window

The parameters are few and sit on plateaus: moving any single one of
the washout depth, breakout lookback, momentum gate or depth check
by ±20% leaves the dev result unchanged or nearly so (the two v2
parameters included - see the tuning note above), because the
gates describe an event (a real capitulation that based and turned),
not a tuned curve fit. On a window that trends up from the open the
bot makes its one fallback trade; on a window that falls and keeps
falling it stays in cash at 0 rather than bleeding costs - it can
only lose meaningfully if a textbook washout base turns out to be a
dead-cat bounce, which the 1.2% hard stop caps at about 1.5% of
equity including costs.
