"""Forex Factory economic calendar — live JSON mirror, HTML scrape, CSV fallback.

Direction mapping for EURUSD:
  EUR event bullish  → buy EURUSD (EUR strength)
  EUR event bearish  → sell EURUSD
  USD event bullish  → sell EURUSD (USD strength)
  USD event bearish  → buy EURUSD
Scores: 0 = strong SELL, 50 = neutral, 100 = strong BUY.

Source order (first that yields rows wins):
  1. live JSON mirror of the FF calendar (no scraping needed)
  2. HTML scrape of forexfactory.com (often 403-blocked — hence #1)
  3. local CSV snapshots (impact names normalized, events date-windowed)
"""
import csv
import datetime as dt
import os
import re
import requests
from ur_pkg.log import Log

log = Log.get("ur")

PAIR_CURRENCIES = ["USD", "EUR"]

FF_JSON_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

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


def _normalize_impact(impact: str) -> str:
    """Map FF impact strings ('Red (High)', 'High', 'Orange (Medium)'...) → high|medium|low."""
    i = (impact or "").strip().lower()
    if not i:
        return ""
    if "high" in i or i == "red":
        return "high"
    if "medium" in i or i == "orange":
        return "medium"
    if "low" in i or i == "yellow":
        return "low"
    return i


def _within_window(date_str: str, days_back: int, days_ahead: int) -> bool:
    """True if a YYYY-MM-DD date falls within [today-back, today+ahead]."""
    try:
        d = dt.date.fromisoformat((date_str or "")[:10])
    except ValueError:
        return True  # unparseable date → keep the row rather than silently drop it
    today = dt.date.today()
    return today - dt.timedelta(days=days_back) <= d <= today + dt.timedelta(days=days_ahead)


def _scrape_ff_json(cfg: dict):
    """Live JSON mirror of the FF calendar (works without HTML scraping)."""
    url = cfg["sources"].get("forex_factory_json", FF_JSON_URL)
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    rows = []
    for ev in r.json() or []:
        cur = (ev.get("country") or "").strip().upper()
        impact = _normalize_impact(ev.get("impact"))
        if cur in PAIR_CURRENCIES and impact in ("high", "medium"):
            rows.append({
                "currency": cur,
                "impact": impact,
                "event": (ev.get("title") or "").strip(),
                "time": (ev.get("date") or ""),
            })
    return rows


def _scrape_ff_html(cfg: dict):
    """Legacy HTML scrape — forexfactory.com often returns 403 without a real browser."""
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
        impact = _normalize_impact(imp_m.group(1) if imp_m else "")
        event = (event_m.group(1) if event_m else "").strip()
        if cur in PAIR_CURRENCIES and impact in ("high", "medium"):
            rows.append({"currency": cur, "impact": impact,
                         "event": event, "time": time_m.group(1) if time_m else ""})
    return rows


def _load_csv_fallback(cfg: dict, days_back: int, days_ahead: int):
    rows = []
    for path in cfg["sources"]["news_csv_fallback"]:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    cur = (row.get("Currency") or "").strip().upper()
                    impact = _normalize_impact(row.get("Impact"))
                    if cur in PAIR_CURRENCIES and impact in ("high", "medium") \
                            and _within_window(row.get("Date"), days_back, days_ahead):
                        rows.append({
                            "currency": cur, "impact": impact,
                            "event": (row.get("Event") or "").strip(),
                            "time": (row.get("Time") or "").strip(),
                        })
        except Exception:
            continue
    return rows


def get_news_signal(cfg: dict) -> dict:
    days_back = int(cfg.get("news_window_back", 1))
    days_ahead = int(cfg.get("news_window_ahead", 7))

    rows, source = [], None

    # 1) live JSON mirror (primary — no scraping)
    try:
        rows = _scrape_ff_json(cfg)
        source = "forexfactory-json"
    except Exception as e:
        log.debug(f"FF JSON mirror failed ({e})")

    # 2) HTML scrape (secondary — often 403)
    if not rows:
        try:
            rows = _scrape_ff_html(cfg)
            source = "forexfactory-live"
        except Exception as e:
            log.debug(f"FF live scrape failed ({e}); trying CSV fallback")

    # 3) local CSV snapshots (impact normalized + date window)
    if not rows:
        rows = _load_csv_fallback(cfg, days_back, days_ahead)
        source = "csv-fallback"

    if not rows:
        return {"available": False, "score": 50, "direction": "NEUTRAL",
                "events_analyzed": 0, "note": "no news data in window"}

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
