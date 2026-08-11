"""TradingView technical-analysis summary (oscillators / moving averages).

Parses the same widget payload TradingView uses for its free TA widget:
BUY/SELL/NEUTRAL counts for oscillators and moving averages → a 0-100 score.
"""
import re
import requests
from ur_pkg.log import Log

log = Log.get("ur")


def get_tv_summary(cfg: dict) -> dict:
    url = cfg["sources"]["tradingview_widget"]
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        text = r.text
    except Exception as e:
        return {"available": False, "error": str(e)[:120]}

    m = re.search(r'"Recommendation"\s*:\s*"([^"]+)"', text)
    rec = m.group(1) if m else ""

    # counts like 10|5|3  (buy|neutral|sell)
    def counts(key):
        mm = re.search(r'"' + key + r'"\s*:\s*\{\s*"counts"\s*:\s*"(\d+)\|(\d+)\|(\d+)"', text)
        if mm:
            return [int(mm.group(1)), int(mm.group(2)), int(mm.group(3))]
        return None

    osc = counts("Oscillators") or [0, 0, 0]
    ma = counts("MovingAverages") or [0, 0, 0]

    total_buy = osc[0] + ma[0]
    total_sell = osc[2] + ma[2]
    total = total_buy + total_sell + osc[1] + ma[1]
    score = round(total_buy / total * 100) if total else 50

    direction = "BUY" if score >= 60 else "SELL" if score <= 40 else "NEUTRAL"

    return {
        "available": True,
        "score": score,
        "direction": direction,
        "recommendation": rec,
        "oscillators": {"buy": osc[0], "neutral": osc[1], "sell": osc[2]},
        "moving_averages": {"buy": ma[0], "neutral": ma[1], "sell": ma[2]},
        "source": "tradingview-widget",
    }
