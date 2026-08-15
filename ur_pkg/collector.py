"""Data collection — pulls live data from all sources into one dict.

Sources:
- spot      : live EURUSD bid/ask via TradingView widget + Yahoo chart
- tv        : TradingView technical-analysis summary (oscillators/MAs)
- news      : Forex Factory economic calendar (live scrape, CSV fallback)
- cme       : CFTC COT positioning (open interest / net speculative)
- cross     : cross-asset regime (DXY, VIX, US10Y)
"""
import threading
from ur_pkg.data import spot, tradingview, technical, news, cme, cross_asset
from ur_pkg.log import Log

log = Log.get("ur")


def collect_all(cfg: dict) -> dict:
    symbol = cfg["symbol"]
    results = {}

    def worker(name, fn):
        try:
            results[name] = fn(cfg)
        except Exception as e:
            log.err(f"{name} source failed: {e}")
            results[name] = {"available": False, "error": str(e)[:120]}

    # NOTE: result keys MUST match the weights keys in config.yaml
    # (technical / tradingview / news / flow / cross_asset) — fusion.py
    # looks them up by name, so a mismatch silently drops the source.
    SOURCES = [
        ("spot", spot.get_spot),
        ("tradingview", tradingview.get_tv_summary),
        ("technical", technical.get_technical_signal),
        ("news", news.get_news_signal),
        ("flow", cme.get_flow_signal),
        ("cross_asset", cross_asset.get_cross_signal),
    ]
    threads = [
        threading.Thread(target=worker, args=(name, fn), daemon=True)
        for name, fn in SOURCES
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=45)

    # Guarantee every expected key exists — a collector thread that exceeds
    # the join timeout (or dies before storing) would otherwise cause a
    # KeyError downstream in ur.py / fusion.py. spot is the anchor.
    for name, _ in SOURCES:
        results.setdefault(name, {"available": False, "error": "collector timeout"})
    return results
