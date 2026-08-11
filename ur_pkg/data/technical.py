"""Local technical indicators — RSI, MACD, EMA cross, Bollinger, ATR.

Computed from real Yahoo Finance 1h candles (no TA-Lib dependency).
Provides the `technical` signal source plus a real ATR for SL/TP sizing.
"""
import requests
from ur_pkg.log import Log

log = Log.get("ur")


# ── helpers ──────────────────────────────────────────────────────────

def _fetch_candles(cfg: dict, ticker: str = "EURUSD=X", interval: str = "1h", range_: str = "5d"):
    url = cfg["sources"]["yahoo_chart"].format(ticker=ticker)
    url = url.replace("interval=1h&range=5d", f"interval={interval}&range={range_}")
    r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    data = r.json()["chart"]["result"][0]
    ts = data.get("timestamp") or []
    q = data.get("indicators", {}).get("quote", [{}])[0]
    closes = q.get("close") or []
    highs = q.get("high") or []
    lows = q.get("low") or []
    rows = []
    for i, t in enumerate(ts):
        if i >= len(closes) or i >= len(highs) or i >= len(lows):
            break
        c, h, l = closes[i], highs[i], lows[i]
        if c is None or h is None or l is None:
            continue
        rows.append({"t": t, "close": float(c), "high": float(h), "low": float(l)})
    return rows


def _ema(values, period):
    if not values:
        return []
    k = 2.0 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0))
        losses.append(max(-ch, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(rows, period=14):
    if len(rows) < period + 1:
        return None
    trs = []
    for i in range(1, len(rows)):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    return atr


def _sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _stddev(values, period):
    if len(values) < period:
        return None
    window = values[-period:]
    mean = sum(window) / period
    var = sum((v - mean) ** 2 for v in window) / period
    return var ** 0.5


# ── signal ───────────────────────────────────────────────────────────

def get_technical_signal(cfg: dict) -> dict:
    try:
        rows = _fetch_candles(cfg)
    except Exception as e:
        return {"available": False, "error": str(e)[:120]}

    if len(rows) < 40:
        return {"available": False, "error": f"insufficient candles ({len(rows)})"}

    closes = [r["close"] for r in rows]
    last = closes[-1]

    rsi = _rsi(closes, 14)
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd = ema12[-1] - ema26[-1]

    # MACD signal line = EMA9 of the MACD series
    macd_series = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
    signal_line = _ema(macd_series, 9)[-1] if len(macd_series) >= 9 else None
    macd_hist = macd - signal_line if signal_line is not None else None

    atr = _atr(rows, 14)
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    sd20 = _stddev(closes, 20)
    bb_upper = (sma20 + 2 * sd20) if sma20 and sd20 else None
    bb_lower = (sma20 - 2 * sd20) if sma20 and sd20 else None

    # ── 0-100 score (mean-reversion + trend mix) ───────────────────
    s_rsi = s_macd = s_ema = s_bb = 50.0

    if rsi is not None:                       # oversold → buy, overbought → sell
        s_rsi = 100 - rsi
    if macd_hist is not None:                 # histogram above 0 → bullish
        s_macd = 65 if macd_hist > 0 else 35
    if sma20 is not None and sma50 is not None:
        if last > sma20 > sma50:
            s_ema = 70
        elif last < sma20 < sma50:
            s_ema = 30
        elif last > sma20:
            s_ema = 58
        else:
            s_ema = 42
    if bb_lower is not None and bb_upper is not None:
        if last <= bb_lower:
            s_bb = 70
        elif last >= bb_upper:
            s_bb = 30
        elif last < sma20:
            s_bb = 42
        else:
            s_bb = 58

    score = round(0.30 * s_rsi + 0.25 * s_macd + 0.25 * s_ema + 0.20 * s_bb)
    score = max(0, min(100, score))
    direction = "BUY" if score >= 60 else "SELL" if score <= 40 else "NEUTRAL"

    return {
        "available": True,
        "score": score,
        "direction": direction,
        "close": last,
        "atr": atr,
        "indicators": {
            "rsi": round(rsi, 1) if rsi is not None else None,
            "macd": round(macd, 6) if macd is not None else None,
            "macd_hist": round(macd_hist, 6) if macd_hist is not None else None,
            "signal": round(signal_line, 6) if signal_line is not None else None,
            "ema20": round(sma20, 5) if sma20 else None,
            "ema50": round(sma50, 5) if sma50 else None,
            "bb_upper": round(bb_upper, 5) if bb_upper else None,
            "bb_lower": round(bb_lower, 5) if bb_lower else None,
            "atr": round(atr, 6) if atr else None,
            "atr_pct": round(atr / last * 100, 3) if atr else None,
        },
        "source": "local-indicators (yahoo 1h)",
    }
