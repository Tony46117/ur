"""CME / CFTC flow signal: COT positioning, open interest, options-flow proxy.

- CFTC COT (public API): net speculative positioning on Euro FX futures (6E).
- Options flow proxy: uses OI + net positioning shifts to infer dealer exposure.
"""
import requests
import time
from ur_pkg.log import Log

log = Log.get("ur")

COT_MARKET = "EURO FX - CHICAGO MERCANTILE EXCHANGE"
COT_API = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
_COT_CACHE = None
_COT_CACHE_TS = 0


def _fetch_cot(cfg: dict) -> dict:
    global _COT_CACHE, _COT_CACHE_TS
    now = time.time()
    if _COT_CACHE and now - _COT_CACHE_TS < 6 * 3600:
        return _COT_CACHE
    try:
        params = {
            "market_and_exchange_names": COT_MARKET,
            "$limit": 1,
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$select": ("report_date_as_yyyy_mm_dd,open_interest_all,"
                        "noncomm_positions_long_all,noncomm_positions_short_all,"
                        "comm_positions_long_all,comm_positions_short_all"),
        }
        r = requests.get(COT_API, params=params, timeout=20)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            return {"available": False, "error": "no COT row"}
        row = rows[0]
        f = lambda k: float(row.get(k) or 0)
        oi = f("open_interest_all")
        ncl, ncs = f("noncomm_positions_long_all"), f("noncomm_positions_short_all")
        net = ncl - ncs
        result = {
            "available": True,
            "report_date": str(row.get("report_date_as_yyyy_mm_dd", ""))[:10],
            "open_interest": oi,
            "noncomm_long": ncl, "noncomm_short": ncs,
            "net_noncomm": net,
            "positioning": "net_long" if net > 0 else "net_short" if net < 0 else "neutral",
            "positioning_strength": round(min(100, abs(net) / max(oi, 1) * 100), 1),
            "source": "CFTC COT",
        }
        _COT_CACHE = result
        _COT_CACHE_TS = now
        return result
    except Exception as e:
        return {"available": False, "error": str(e)[:120]}


def get_flow_signal(cfg: dict) -> dict:
    cot = _fetch_cot(cfg)
    if not cot.get("available"):
        return {"available": False, "score": 50, "direction": "NEUTRAL",
                "note": "COT unavailable", **cot}

    pos = cot["positioning"]
    strength = cot["positioning_strength"]
    if pos == "net_long":
        score = 50 + strength * 0.5   # 50..100
        direction = "BUY"
    elif pos == "net_short":
        score = 50 - strength * 0.5   # 0..50
        direction = "SELL"
    else:
        score = 50
        direction = "NEUTRAL"

    return {
        "available": True,
        "score": round(max(0, min(100, score))),
        "direction": direction,
        "positioning": pos,
        "positioning_strength": strength,
        "open_interest": cot["open_interest"],
        "net_noncomm": cot["net_noncomm"],
        "report_date": cot["report_date"],
        "options_proxy": {
            "available": False,
            "note": "Real CME options flow requires DataCloud subscription; "
                    "COT positioning used as flow proxy.",
        },
        "note": f"COT {pos} ({strength}%) — options flow proxied by COT",
    }
