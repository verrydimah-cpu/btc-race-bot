# btc-race-bot

A cbBTC/USDC trading bot for the make.fun bounty
**btc-race-24h-20261118-1444** ("Race a BTC trading bot live for 24
hours"), entered by @verry-dimah.

The bot speaks `agent-fun/bars-replay/v1` (NDJSON on stdin/stdout)
and runs as `python3 -P -s /bot/main.py` on Python 3.13, standard
library only. It trades one pattern - a washout reversal: it arms
when the close has fallen at least 1.2% from its 480-bar high with a
peak-to-trough fall of at least 1.8%, waits for a 60-bar base, and
buys the turn out of the base (10-bar high break, rising hour, still
near the lows), with structure, hard-stop, profit-trail,
armed-phase-fuse and time-stop exits and volatility-scaled sizing. A small late-window
uptrend fallback guarantees a trade on windows whose only pattern
was strength. See [STRATEGY.md](STRATEGY.md) for the full
description and the dev-window results.

## Layout

- `main.py` - the bot (all strategy code lives here).
- `vendor/makefun_bars.py` - a byte-identical copy of the kit's
  Python SDK shim (`sdk/makefun_bars.py`); it owns the wire protocol
  so `main.py` only decides orders.
- `STRATEGY.md` - the strategy, honestly described.
- `LICENSE` - MIT.

## Properties

- Deterministic: no wall clock, no environment reads, no randomness;
  two runs over the same window produce byte-identical replies.
- Dev window (kit dataset, exact harness fill model): net PnL
  +19.23 USDC on 1,000 USDC, 1 round trip, max drawdown 0.65% -
  above the dev gate's break-even after all fees, slippage and
  price impact.
