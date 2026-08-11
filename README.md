# ur — Autonomous EURUSD Trading Software

`ur` launches your MT5 terminal (via the Bottles **mt5** bottle), collects
live market data from multiple sources, fuses everything into one trade
decision, and executes it into the running terminal — with a **paper
fallback** when the terminal can't be attached programmatically.

## Quick start

```bash
pip install -r requirements.txt
python3 ur.py            # full run: launch → collect → decide → execute
python3 ur.py --dry-run  # analyze only, no order
python3 ur.py --lot 0.47 # fixed lot override
python3 ur.py --diagram  # regenerate architecture diagram
```

## Pipeline

```
ur.py → launcher (bottles-cli → mt5 bottle → MT5 terminal)
      → collectors (Forex Factory · TradingView · Yahoo spot · CFTC COT)
      → fusion engine (weighted scores + agreement + conviction)
      → risk manager (ATR SL/TP · lot sizing)
      → executor (MetaTrader5 order_send in-bottle · paper fallback)
```

## Data sources

| Source | Data | Fallback |
|---|---|---|
| Forex Factory | economic calendar (high/medium USD+EUR) | local news CSVs |
| TradingView | TA widget summary (oscillators/MAs) | — |
| Yahoo Finance | live EURUSD spot, DXY, VIX, US10Y | — |
| CFTC COT API | Euro FX open interest + net positioning | — |
| CME options | flow proxied from COT | DataCloud if subscribed |

## Execution

- **live**: runs Wine-Python inside the same bottle, attaches to the
  running terminal via the `MetaTrader5` pip package and calls
  `order_send()`. If the terminal build doesn't match the pip package
  (error -6), or the account isn't logged in, it records a **paper fill**
  to `paper_trades.json` instead and tells you why.
- **paper**: simulates the fill (default when `execution.mode: paper`).

## Config

Everything lives in `config.yaml` (weights, risk, lot override, bottle
name, keys file path). API keys are read from your `apis.txt` at runtime
and are never committed to the repository.
