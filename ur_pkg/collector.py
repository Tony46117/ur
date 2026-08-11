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

    threads = [
        threading.Thread(target=worker, args=("spot", spot.get_spot)),
        threading.Thread(target=worker, args=("tv", tradingview.get_tv_summary)),
        threading.Thread(target=worker, args=("technical", technical.get_technical_signal)),
        threading.Thread(target=worker, args=("news", news.get_news_signal)),
        threading.Thread(target=worker, args=("cme", cme.get_flow_signal)),
        threading.Thread(target=worker, args=("cross", cross_asset.get_cross_signal)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=45)

    # spot is the anchor — other modules may need it
    results.setdefault("spot", {"available": False})
    return results
