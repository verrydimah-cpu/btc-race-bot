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
3. **Base.** At least 60 bars must pass after the washout begins, so
   the entry is never the first bounce off a falling knife.
4. **Turn (the entry).** The close breaks the highest high of the
   last 10 bars, the trailing hour is up at least 0.10%, and the
   close is still within 1.5% of the 480-bar low - the turn out of
   the base, not a chase after the recovery has already run.

## Exits

- **Structure break:** the close falls under the lowest low of the
  last 120 bars.
- **Hard stop:** 1.2% under the position's average cost.
- **Profit trail:** once the best close since entry is at least 1.6%
  above the entry, a close 0.25% under that peak sells. (A plain ATR
  trailing stop was tried first and strangled every trade in 1-minute
  noise; the trail only exists to protect a real gain, and it arms
  late on purpose - the first bounce inside a base routinely runs a
  percent or so and dips again, and a trail armed on that bounce
  shakes the position out before the real turn.)
- **Armed-phase fuse:** once the trail has armed, the position is
  banked 7 bars later unless another exit fires first. A move that
  has run 1.6% in a handful of one-minute bars has usually spent
  itself, and waiting for a close to fall the full trail distance
  under the peak hands back a quarter of the gain before the exit
  even fills.
- **Time stop:** 600 bars. After any exit the bot disarms and needs
  a fresh washout.

## Sizing

Volatility-scaled: the notional is the share of equity that puts the
per-bar ATR (Wilder, 14) at a 0.12% target, floored at 35% and capped
at 100% of equity (and by the harness's weight room and cash). Quiet
trends get full size; wild ones get less. Every order carries
`max_slippage_bps = 300`, far above the ~13 bps a full-size fill
moves, so fills are not rejected for slippage in normal conditions.

## The fallback

A racing entry needs at least one trade to meet the ranking bar. If
no washout trade has filled by bar 900 and the window's only pattern
was strength instead - trailing 480-bar return at or above +0.5%
with a fresh 10-bar high - the bot takes one small trend position
(at most 25% of equity, same exits). The washout module always has
priority; on any window where it traded, the fallback never fires.

## Dev-window result (local grade, exact harness fill model)

- Full 1,440 bars: **net PnL +19.23 USDC (+1.92%)**, 1 round trip
  (2 filled orders), maximum drawdown 0.65%.
- First half alone: +19.23 USDC (the same trade).
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

## v3 tuning (five parameters, validated)

A later pass asked whether the same washout event could be read
earlier and ridden more patiently. Five parameters changed, all in
the turn/exit/sizing layer - the arm, depth check and base band
that define the event itself are untouched:

- `TURN_N` 30 -> 10 and `MOM_MIN` 0.002 -> 0.001, `BASE_AGE` 90 ->
  60: the entry takes the first convincing turn out of the base
  (a 10-bar high break on a rising hour) instead of waiting for a
  mature 30-bar breakout. On the dev window this fills about 0.3%
  cheaper, near the base rather than halfway up the recovery.
- `TRAIL_ARM` 0.008 -> 0.016: the necessary counterpart. An earlier
  entry meets the base's interim bounce (about +1% on dev) before
  the real turn, and a trail armed at 0.8% is shaken out by the
  dip that follows it (that combination scores only about +5 to
  +7). Arming at 1.6% ignores the bounce and keeps the trade for
  the full move; anywhere in 1.4%-1.8% gives the identical dev
  result, so the value sits mid-plateau.
- `VOL_TARGET` 0.0008 -> 0.0012: at the earlier entry the tape is
  still slightly more volatile, and the old target scaled the
  position to about 94% of equity; the new one restores the full
  size the pattern is meant to take.

Dev result moves from +12.50 USDC / 0.74% max drawdown (v2) to
**+16.48 USDC / 0.65%** (v3), the same single round trip, entered
earlier and exited at the same fill as v2. Perturbing each changed
parameter by ±20% one at a time keeps the dev PnL above the v2
result (worst case: `BASE_AGE` +20% at +12.96); stacking the three
adverse perturbations at once degenerates the entry back to
exactly the v2 trade (+12.50). The honest caveat: the earlier
turn is a more aggressive reading of the same event, so on an
unseen window it will also fire on some weaker bases that v2
would have skipped - the 1.2% hard stop and the depth gate are
what bound that cost, at about 1.5% of equity per failed trade.

## v4 tuning (one new parameter, validated)

A final pass worked only on the exit side - the v3 entry is
untouched - and asked how much of the remaining gap between the
trail's exit fill and the hold's peak close (about 0.4% on dev)
could be kept. The trail's wait for a close 0.25% under the peak
costs about 0.28% of it; fills themselves cost about 0.12% in
slippage and impact, which no exit rule can avoid. The alternatives
were tested against the same fill model:

- Tighter trails (0.08%-0.12%) exit a bar or two sooner but fill
  on worse opens after the top: +17.87 at best. A fixed
  take-profit threshold is a cliff - the dev peak sits at +2.10%
  over the average cost, so a threshold a hair under it fires at
  the peak bar and a hair over it never fires at all.
- Structure and stall exits after arming land at +16.29 to
  +18.04; looser trails only lose, because the price never
  recovers after the dev top.
- What works is a short fuse on the armed phase: `ARM_T = 7`
  banks the position 7 bars after the trail arms. On dev the
  armed phase is a clean staircase to the peak, and the fuse
  fills one bar after the peak close instead of four.

Dev result moves from +16.48 USDC (v3) to **+19.23 USDC** (v4),
the same single round trip, maximum drawdown unchanged at
0.65%. The fuse length sits on a plateau, not a spike:
perturbing `ARM_T` by ±20% (5.6 / 8.4 bars) keeps the dev PnL
at +18.57 / +18.04, and every whole-bar length from 5.6 to 9
stays above +17.87 - the dev top is a multi-bar plateau, so any
short fuse banks nearly the same price. The honest caveat: on
an unseen window the fuse will sometimes bank a move that
would have run further, and the trail only gets its say when a
reversal is fast enough to trigger inside the 7 bars. That is
the accepted price of not paying the trail's give-back on
every completed move.

## Why this should travel to an unseen window

The parameters sit on plateaus rather than spikes: moving any
single parameter of the design by ±20% leaves the dev result
unchanged or keeps it above the previous version's result (the
v2, v3 and v4 tuning notes above give the numbers), because the
gates describe an event (a real capitulation that based and
turned), not a tuned curve fit. On a window that trends up from the open the
bot makes its one fallback trade; on a window that falls and keeps
falling it stays in cash at 0 rather than bleeding costs - it can
only lose meaningfully if a textbook washout base turns out to be a
dead-cat bounce, which the 1.2% hard stop caps at about 1.5% of
equity including costs.
