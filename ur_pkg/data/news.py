"""Forex Factory economic calendar — live scrape with CSV fallback.

Direction mapping for EURUSD:
  EUR event bullish  → buy EURUSD (EUR strength)
  EUR event bearish  → sell EURUSD
  USD event bullish  → sell EURUSD (USD strength)
  USD event bearish  → buy EURUSD
Scores: 0 = strong SELL, 50 = neutral, 100 = strong BUY.
"""
import csv
import os
import re
import time
import requests
from ur_pkg.log import Log

log = Log.get("ur")

PAIR_CURRENCIES = ["USD", "EUR"]

# event keyword → bias for THAT currency (higher inflation → currency bullish)
_BIAS_RULES = [
    (r"cpi|inflation|ppi|price index", "bullish"),
    (r"non-farm|employment|payroll|jobs", "bullish"),
    (r"unemployment|jobless|claims", "bearish"),  # rising unemployment → currency bearish
    (r"gdp|growth", "bullish"),
    (r"retail sales|consumer spending", "bullish"),
    (r"interest rate|fomc|ecb|rate decision", "neutral"),
    (r"trade balance|current account", "neutral"),
    (r"ism|pmi|sentix|zew|confidence", "bullish"),
    (r"industrial production", "bullish"),
]

_IMPACT_WEIGHT = {"high": 3.0, "medium": 1.5, "low": 0.5}


def _scrape_ff(cfg: dict):
    url = cfg["sources"]["forex_factory_url"]
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    html = r.text
    rows = []
    for rm in re.finditer(r'<tr[^>]*class="[^"]*calendar__row[^"]*"[^>]*>(.*?)</tr>', html, re.S):
        block = rm.group(1)
        cur_m = re.search(r'class="calendar__currency[^"]*"[^>]*>\s*([A-Z]{3})', block)
        imp_m = re.search(r'class="calendar__impact[^"]*"[^>]*>\s*<[^>]*>\s*<span[^>]*title="([^"]+)"', block)
        event_m = re.search(r'class="calendar__event[^"]*"[^>]*>\s*(?:<[^>]*>)*\s*([A-Za-z0-9 /,.()\-]+)', block)
        time_m = re.search(r'class="calendar__time[^"]*"[^>]*>\s*([\d:apm]+)', block)
        cur = cur_m.group(1) if cur_m else ""
        impact = (imp_m.group(1) if imp_m else "").lower()
        event = (event_m.group(1) if event_m else "").strip()
        if cur in PAIR_CURRENCIES and impact in ("high", "medium"):
            rows.append({"currency": cur, "impact": impact,
                         "event": event, "time": time_m.group(1) if time_m else ""})
    return rows


def _load_csv_fallback(cfg: dict):
    rows = []
    for path in cfg["sources"]["news_csv_fallback"]:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    cur = (row.get("Currency") or "").strip().upper()
                    impact = (row.get("Impact") or "").lower()
                    if cur in PAIR_CURRENCIES and impact in ("high", "medium"):
                        rows.append({
                            "currency": cur, "impact": impact,
                            "event": (row.get("Event") or "").strip(),
                            "time": (row.get("Time") or "").strip(),
                        })
        except Exception:
            continue
    return rows


def get_news_signal(cfg: dict) -> dict:
    rows = []
    source = "csv-fallback"
    try:
        rows = _scrape_ff(cfg)
        source = "forexfactory-live"
    except Exception as e:
        log.debug(f"FF live scrape failed ({e}); using CSV fallback")
        rows = _load_csv_fallback(cfg)

    if not rows:
        return {"available": False, "score": 50, "direction": "NEUTRAL",
                "events_analyzed": 0, "note": "no news data"}

    buy = sell = total_w = 0.0
    details = []
    for row in rows:
        w = _IMPACT_WEIGHT.get(row["impact"], 1.0)
        event = row["event"]
        currency = row["currency"]
        bias = "neutral"
        for pat, b in _BIAS_RULES:
            if re.search(pat, event, re.I):
                bias = b
                break

        # map currency bias → EURUSD pair direction
        if bias == "neutral":
            pair_bias = "neutral"
        elif currency == "EUR":
            pair_bias = bias                      # EUR bullish → EURUSD buy
        else:  # USD
            pair_bias = {"bullish": "bearish", "bearish": "bullish"}[bias]

        total_w += w
        if pair_bias == "bullish":
            buy += w
        elif pair_bias == "bearish":
            sell += w
        else:
            buy += w * 0.5
            sell += w * 0.5

        details.append({"event": event[:60], "currency": currency,
                        "impact": row["impact"], "currency_bias": bias,
                        "pair_bias": pair_bias})

    score = round(buy / total_w * 100) if total_w else 50
    direction = "BUY" if score >= 60 else "SELL" if score <= 40 else "NEUTRAL"
    return {
        "available": True, "score": score, "direction": direction,
        "events_analyzed": len(rows), "source": source, "details": details[:8],
        "note": f"{len(rows)} events from {source}",
    }
