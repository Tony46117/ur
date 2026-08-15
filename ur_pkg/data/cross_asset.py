"""Cross-asset regime signal: DXY, VIX, US 10Y via Yahoo chart."""
import requests
from ur_pkg.log import Log

log = Log.get("ur")


def get_cross_signal(cfg: dict) -> dict:
    tickers = cfg["sources"]["cross_asset_tickers"]
    values = {}
    for name, ticker in tickers.items():
        try:
            url = cfg["sources"]["yahoo_chart"].format(ticker=ticker)
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            meta = r.json()["chart"]["result"][0]["meta"]
            price = float(meta.get("regularMarketPrice") or 0)
            prev = float(meta.get("chartPreviousClose") or price)
            values[name] = {"price": price, "chg_pct": (price - prev) / prev * 100 if prev else 0}
        except Exception as e:
            values[name] = {"available": False, "error": str(e)[:80]}

    # available only if at least one ticker actually loaded
    if not any(isinstance(v, dict) and v.get("available") is not False for v in values.values()):
        return {"available": False, "score": 50, "direction": "NEUTRAL",
                "values": values, "note": "cross-asset data unavailable",
                "error": "all tickers failed"}

    # Risk regime logic for EURUSD
    dxy = values.get("DXY", {}).get("chg_pct")
    vix = values.get("VIX", {}).get("price")
    us10 = values.get("US10Y", {}).get("chg_pct")

    score = 50.0
    reasons = []
    if dxy is not None:
        score -= dxy * 4.0                      # weak USD → bullish EUR
        reasons.append(f"DXY {dxy:+.2f}%")
    if vix:
        if vix > 25:
            score -= 12; reasons.append(f"VIX {vix:.1f} risk-off")
        elif vix < 15:
            score += 8; reasons.append(f"VIX {vix:.1f} risk-on")
        else:
            reasons.append(f"VIX {vix:.1f}")
    if us10 is not None:
        score += us10 * 2.0                     # rising yields → risk-off, mild EUR drag
        reasons.append(f"US10Y {us10:+.2f}%")

    score = round(max(0, min(100, score)))
    direction = "BUY" if score >= 60 else "SELL" if score <= 40 else "NEUTRAL"
    return {
        "available": True, "score": score, "direction": direction,
        "values": values, "reasons": reasons,
        "note": "; ".join(reasons) if reasons else "cross-asset flat",
    }
