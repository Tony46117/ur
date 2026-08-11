"""Live spot price — Yahoo Finance quote (primary, reliable)."""
import requests

YAHOO_TICKER = "EURUSD=X"


def get_spot(cfg: dict) -> dict:
    try:
        url = cfg["sources"]["yahoo_chart"].format(ticker=YAHOO_TICKER)
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        meta = r.json()["chart"]["result"][0]["meta"]
        price = float(meta.get("regularMarketPrice") or 0)
        if not price:
            return {"available": False, "error": "empty price from yahoo"}
        return {
            "available": True,
            "price": price,
            "bid": price,
            "ask": price,
            "source": "yahoo-chart",
            "time": meta.get("regularMarketTime"),
            "prev_close": meta.get("chartPreviousClose"),
        }
    except Exception as e:
        return {"available": False, "error": str(e)[:120]}
