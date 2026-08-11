"""Fusion engine — combine all signal sources into one trade decision.

Weights (config): technical 0.30, tradingview 0.20, news 0.20,
flow 0.15, cross_asset 0.15.

Outputs direction BUY/SELL/HOLD, score 0-100, conviction, agreement,
entry/SL/TP based on ATR and config risk multipliers.
"""
from ur_pkg.log import Log

log = Log.get("ur")

ATR_FALLBACK = 0.0015   # ~15 pips — only if no live ATR available


def _source_score(cfg, data, key, default=50):
    s = data.get(key, {})
    if s.get("available"):
        return float(s.get("score", default))
    return None


def _get_atr(data: dict):
    """Real ATR from the local technical module when available."""
    tech = data.get("technical", {})
    if tech.get("available") and tech.get("atr"):
        return float(tech["atr"])
    return ATR_FALLBACK


def decide(cfg: dict, data: dict) -> dict:
    weights = cfg["weights"]
    spot = data.get("spot", {})
    price = spot.get("price") if spot.get("available") else None

    comps = {}
    present = 0
    for key, w in weights.items():
        sc = _source_score(cfg, data, key)
        if sc is not None:
            comps[key] = round(sc)
            present += 1
        else:
            comps[key] = None

    if present == 0:
        return {
            "direction": "HOLD", "score": 50, "conviction": "LOW",
            "agreement": "NONE", "verdict": "HOLD — no data sources available",
            "entry": price, "sl": None, "tp": None, "rr": 0,
            "components": comps, "price": price,
        }

    # renormalize weights over available sources
    active_w = sum(weights[k] for k in comps if comps[k] is not None) or 1.0
    score = sum((comps[k] or 50) * weights[k] for k in comps if comps[k] is not None) / active_w
    score = round(max(0, min(100, score)))

    # agreement: count BUY/SELL/NEUTRAL among directional sources
    dirs = []
    for key in weights:
        s = data.get(key, {})
        if s.get("available") and s.get("direction") in ("BUY", "SELL", "NEUTRAL"):
            dirs.append(s["direction"])
    buys = dirs.count("BUY")
    sells = dirs.count("SELL")
    neut = dirs.count("NEUTRAL")

    if buys >= 3:
        agreement = "ALIGNED"
    elif sells >= 3:
        agreement = "ALIGNED"
    elif buys >= 2 and sells >= 2:
        agreement = "CONFLICTING"
    elif buys >= 2 or sells >= 2:
        agreement = "PARTIAL"
    else:
        agreement = "NEUTRAL"

    direction = "BUY" if score >= 60 else "SELL" if score <= 40 else "HOLD"

    # conviction
    dist = abs(score - 50)
    if agreement == "ALIGNED":
        conv_base = 45 + dist
    elif agreement == "PARTIAL":
        conv_base = 30 + dist
    else:
        conv_base = 15 + dist
    conviction = "HIGH" if conv_base >= 70 else "MEDIUM" if conv_base >= 40 else "LOW"

    # verdict text
    if direction == "HOLD":
        verdict = f"HOLD EURUSD — score {score}, agreement {agreement} ({buys}B/{sells}S/{neut}N). No edge."
    elif agreement == "ALIGNED":
        verdict = f"{direction} EURUSD — {score}/100, {agreement}, conviction {conviction}. Strong confluence."
    elif agreement == "PARTIAL":
        verdict = f"{direction} EURUSD — {score}/100, {agreement}. Trade with caution."
    else:
        verdict = f"{direction} EURUSD — {score}/100, conflicting sources ({agreement}). Small size only."

    # ATR for SL/TP — real ATR(14) from local indicators when available
    atr = _get_atr(data)
    pip = 0.0001
    sl_dist = atr * cfg["risk"]["sl_atr_mult"]
    tp_dist = atr * cfg["risk"]["tp1_atr_mult"]

    entry = price
    sl = tp = None
    rr = 0.0
    if price and direction in ("BUY", "SELL"):
        if direction == "BUY":
            sl = price - sl_dist
            tp = price + tp_dist
        else:
            sl = price + sl_dist
            tp = price - tp_dist
        rr = round(abs(tp - price) / max(abs(sl - price), 1e-12), 2)

    return {
        "direction": direction,
        "score": score,
        "conviction": conviction,
        "agreement": agreement,
        "verdict": verdict,
        "entry": entry,
        "sl": round(sl, 5) if sl else None,
        "tp": round(tp, 5) if tp else None,
        "rr": rr,
        "atr": atr,
        "components": comps,
        "price": price,
        "technical": data.get("technical", {}).get("indicators"),
    }
