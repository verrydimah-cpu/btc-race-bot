"""Washout-reversal bot for cbBTC/USDC, agent-fun/bars-replay/v1.

Long only, one position at most. A full-size round trip costs roughly
26 bps in fees, slippage and price impact, and most 24-hour windows are
drift and chop in which almost every long entry bleeds those costs. So
this bot trades one pattern only, the one with room to pay for itself:
a capitulation that has stopped falling and turned.

  - Arm: the close has fallen at least WASH_MIN below the highest
    close of the last WASH_L bars - a real washout, not a dip. The
    arm holds until the close recovers to the washout peak, and the
    base must have BASE_AGE bars to form before an entry counts.
  - Enter (while armed): the episode's fall from its peak must have
    reached DEPTH_MIN peak to trough (a routine pullback off a local
    high does not count), the close breaks the highest high of the
    last TURN_N bars with the trailing hour up at least MOM_MIN, and
    the close is still within BASE_BAND of the WASH_L-bar low - the
    turn out of the base, not a chase after the move has run.
  - Exit: the close breaks the lowest low of the last EXIT_L bars
    (the base/trend structure is gone), a hard stop STOP_PCT under
    the entry, a profit trail that arms only after a real gain (peak
    TRAIL_ARM above the entry, then out TRAIL_PCT under the peak), an
    armed-phase fuse that banks the position ARM_T bars after the
    trail arms, or a time stop. TRAIL_ARM is deliberately high (v3): the first
    bounce inside a base routinely runs a percent or so and then
    dips again, and a trail armed on that bounce shakes the position
    out before the real turn; arming only once the reversal has
    proven itself keeps the trade on for the move that pays. The
    fuse is the counterpart on the way out: once a move has run
    TRAIL_ARM in a handful of one-minute bars it has usually spent
    itself, and waiting for a close to fall TRAIL_PCT under the
    peak hands back a quarter of the gain, so the position is
    banked ARM_T bars after arming unless another exit fires
    first. After any exit the bot disarms: a fresh washout must
    arm it again.

Position size scales down as volatility rises (ATR / close). Outside
the pattern the bot holds cash: on a window with no washout it makes
no trade and exactly 0, which the dev gate rejects - deliberately,
because a forced trade in chop is how the costs get paid for nothing.

One exception, late in the window: if no washout trade has filled by
bar FALLBACK_FROM and the tape is in a clean uptrend instead (trailing
WASH_L return at or above FB_TREND with a fresh TURN_N high), the bot
takes one small trend position (at most FB_FRAC of equity). A racing
entry needs at least one trade to rank at all, and a small confirmed
trend trade is the cheapest honest way to have one on a window whose
only pattern was strength, not capitulation. The washout module
always has priority, and on any window where it traded, this fallback
never fires.

Everything is computed from the bars alone: no clock, no environment,
no randomness, so two runs over the same window answer byte for byte
alike.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

# --- strategy parameters (kept few on purpose: robustness over fit) ---
WASH_L = 480             # lookback for the washout peak (partial early on)
WASH_MIN = -0.012        # close this far under the WASH_L high arms the bot
RECOVER = 0.003          # arm ends when the close recovers to the peak
DEPTH_MIN = 0.018        # the episode must fall this far peak to trough
BASE_AGE = 60            # bars the base must form before an entry counts (v3: was 90)
TURN_N = 10              # breakout lookback for the turn out of the base (v3: was 30)
MOM_L = 60               # momentum gate lookback at the entry
MOM_MIN = 0.001          # trailing hour up at least this much (v3: was 0.002, v1 0.0025)
BASE_BAND = 0.015        # enter only within 1.5% of the WASH_L-bar low
EXIT_L = 120             # structure-break lookback while held
ADX_PERIOD = 14          # (ATR comes from the same Wilder engine)
VOL_TARGET = 0.0012      # per-bar ATR/close the sizing aims at (v3: was 0.0008)
MIN_FRAC = 0.35          # never size below this share of equity
TRAIL_ARM = 0.016        # profit trail arms this far above the entry (v3: was 0.008)
TRAIL_PCT = 0.0025       # exits this far under the peak close (v2: was 0.004)
ARM_T = 7                # bars after the trail arms before the position is banked (v4)
STOP_PCT = 0.012         # hard stop: 1.2% under the entry price
TIME_STOP = 600          # bars; a reversal older than this is sold
FALLBACK_FROM = 900      # bar from which the fallback may arm
FB_TREND = 0.005         # trailing WASH_L return that counts as an uptrend
FB_FRAC = 0.25           # the fallback's cap on position size (of equity)
MAX_SLIPPAGE_BPS = 300


class Wilder:
    """Wilder-smoothed TR giving ATR (period p)."""

    def __init__(self, period):
        self.p = period
        self.prev = None       # previous bar (h, l, c) as floats
        self.tr_sum = 0.0      # seed accumulation, then the smoothed sum
        self.seen = 0

    def step(self, high, low, close):
        if self.prev is None:
            self.prev = (high, low, close)
            return
        ph, pl, pc = self.prev
        self.prev = (high, low, close)
        tr = max(high - low, abs(high - pc), abs(low - pc))
        p = self.p
        if self.seen < p:
            self.tr_sum += tr
            self.seen += 1
        else:
            self.tr_sum = self.tr_sum - self.tr_sum / p + tr

    @property
    def atr(self):
        if self.seen < self.p:
            return None
        return self.tr_sum / self.p


class Series:
    """All per-symbol indicator state."""

    def __init__(self):
        self.wilder = Wilder(ADX_PERIOD)
        self.closes = []
        self.highs = []
        self.lows = []
        self.armed = False     # price sits in a washout drawdown
        self.arm_since = 0     # bar count when this washout episode began
        self.wash_peak = None  # the peak the current washout fell from
        self.ep_low = None     # lowest low since the washout armed
        self.peak = None       # best close since the position was seen held
        self.entry_ref = None  # average cost price (raw units) of the position
        self.held_bars = 0     # batches seen while the position is held
        self.arm_bar = None    # bar count when the profit trail armed
        self.traded = False    # a position has been held at some point


SERIES = {}


def _entry_price(state, symbol, held):
    """Average cost per unit of the held position, in raw price units."""
    info = state.symbols[symbol]
    num = held.cost * 10 ** (info["qty_scale"] + info["price_scale"])
    den = held.qty * 10 ** state.hello["capital"]["quote_scale"]
    return num / den


def on_batch(state, batch):
    fresh = {}
    for bar in batch["bars"]:
        fresh[bar["symbol"]] = bar
    orders = []
    for info in state.hello["symbols"]:
        symbol = info["symbol"]
        bar = fresh.get(symbol)
        if bar is None:
            continue
        s = SERIES.setdefault(symbol, Series())
        close = float(bar["c"])
        s.wilder.step(float(bar["h"]), float(bar["l"]), close)
        s.closes.append(close)
        s.highs.append(float(bar["h"]))
        s.lows.append(float(bar["l"]))

        # Washout arming: the close is at least WASH_MIN under the
        # highest close of the last WASH_L bars; the arm then holds
        # until the close recovers to that peak.
        if len(s.closes) >= 120:
            if s.armed:
                if float(bar["l"]) < s.ep_low:
                    s.ep_low = float(bar["l"])
                if close >= s.wash_peak * (1.0 - RECOVER):
                    s.armed = False
                    s.wash_peak = None
                    s.ep_low = None
            else:
                peak = max(s.closes[-WASH_L:])
                if close <= peak * (1.0 + WASH_MIN):
                    s.armed = True
                    s.arm_since = len(s.closes)
                    s.wash_peak = peak
                    s.ep_low = float(bar["l"])

        held = state.positions.get(symbol)
        if held is not None and held.qty > 0:
            s.traded = True
            if s.entry_ref is None:
                s.entry_ref = _entry_price(state, symbol, held)
                s.peak = close
                s.held_bars = 0
            else:
                s.held_bars += 1
                if close > s.peak:
                    s.peak = close
                if (s.arm_bar is None and s.entry_ref is not None
                        and s.peak >= s.entry_ref * (1.0 + TRAIL_ARM)):
                    s.arm_bar = len(s.closes) - 1
        else:
            s.entry_ref = None
            s.peak = None
            s.held_bars = 0
            s.arm_bar = None

        if state.warming_up:
            continue

        if held is not None and held.qty > 0:
            exit_now = False
            if len(s.lows) > EXIT_L and close < min(s.lows[-1 - EXIT_L:-1]):
                exit_now = True
            if (s.entry_ref is not None and s.peak is not None
                    and s.peak >= s.entry_ref * (1.0 + TRAIL_ARM)
                    and close <= s.peak * (1.0 - TRAIL_PCT)):
                exit_now = True
            if s.arm_bar is not None and len(s.closes) - 1 - s.arm_bar >= ARM_T:
                exit_now = True
            if s.entry_ref is not None and close <= s.entry_ref * (1.0 - STOP_PCT):
                exit_now = True
            if s.held_bars >= TIME_STOP:
                exit_now = True
            if exit_now:
                orders.append({
                    "side": "sell",
                    "symbol": symbol,
                    "qty": held.qty,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                })
                s.armed = False
                s.wash_peak = None
                s.ep_low = None
            continue

        # Flat. Two ways in, the washout first; both share the sizing
        # and order code below, with their own fraction cap.
        atr = s.wilder.atr
        if atr is None or close <= 0.0:
            continue
        if len(s.highs) <= TURN_N or len(s.closes) <= MOM_L:
            continue
        frac_cap = None
        if (s.armed and s.ep_low is not None
                and s.ep_low <= s.wash_peak * (1.0 - DEPTH_MIN)
                and len(s.closes) - s.arm_since >= BASE_AGE
                and close > max(s.highs[-1 - TURN_N:-1])
                and close / s.closes[-1 - MOM_L] - 1.0 >= MOM_MIN
                and close <= min(s.lows[-WASH_L:]) * (1.0 + BASE_BAND)):
            frac_cap = 1.0
            s.armed = False
            s.wash_peak = None
            s.ep_low = None
        elif (not s.traded and len(s.closes) >= FALLBACK_FROM
                and len(s.closes) > WASH_L
                and close / s.closes[-1 - WASH_L] - 1.0 >= FB_TREND
                and close > max(s.highs[-1 - TURN_N:-1])):
            frac_cap = FB_FRAC
        if frac_cap is None:
            continue
        atr_ratio = atr / close
        frac = VOL_TARGET / atr_ratio if atr_ratio > 0.0 else 1.0
        if frac > frac_cap:
            frac = frac_cap
        if frac < MIN_FRAC and frac_cap >= MIN_FRAC:
            frac = MIN_FRAC
        notional = int(state.equity * frac)
        room = state.weight_room(symbol)
        if room < notional:
            notional = room
        if state.cash < notional:
            notional = state.cash
        min_notional = int(state.hello["fees"]["min_notional_quote_units"])
        if notional < min_notional:
            continue
        orders.append({
            "side": "buy",
            "symbol": symbol,
            "notional_quote_units": notional,
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
        })
        s.armed = False
        s.wash_peak = None
        s.ep_low = None
    return orders


if __name__ == "__main__":
    makefun_bars.run(on_batch)
