"""Executor — places the trade into the running MT5 terminal.

Two paths:
1. live : runs a Wine-Python helper (same bottle) that attaches to the
          running terminal via the MetaTrader5 pip package and calls
          order_send(). Falls back to paper on any failure (build
          mismatch, no connection, account not logged in).
2. paper: simulates the fill and records it to paper_trades.json.
"""
import json
import os
import subprocess
import time
import shutil
from ur_pkg.log import Log

log = Log.get("ur")


def _lot(cfg: dict, price: float, sl: float) -> float:
    r = cfg["risk"]
    override = float(r.get("lot_override") or 0)
    if override > 0:
        return round(min(override, float(r.get("max_lot", 5))), 2)
    # risk-based: pip value for EURUSD ≈ $10 per 1.0 lot per pip
    risk_usd = cfg["risk"]["paper_balance"] * (r["risk_percent"] / 100.0)
    sl_pips = abs(price - sl) / 0.0001
    lot = risk_usd / (sl_pips * 10.0) if sl_pips > 0 else 0.01
    return round(max(0.01, min(lot, float(r.get("max_lot", 5)))), 2)


def _wine_python(cfg: dict):
    """Path to the Windows Python inside the mt5 bottle (if present)."""
    prefix = os.path.expanduser(cfg["bottle"]["prefix"])
    return os.path.join(prefix, "drive_c", "Python310", "python.exe")


def _build_order_script(cfg: dict, decision: dict, lot: float) -> str:
    direction = 0 if decision["direction"] == "BUY" else 1  # POSITION_TYPE_BUY/SELL
    return f"""
import json, sys
import MetaTrader5 as mt5

ok = mt5.initialize()
if not ok:
    print(json.dumps({{"ok": False, "error": "init:" + str(mt5.last_error())}}))
    sys.exit(0)

info = mt5.account_info()
if info is None:
    print(json.dumps({{"ok": False, "error": "no-account:" + str(mt5.last_error())}}))
    mt5.shutdown(); sys.exit(0)

request = {{
    "action": mt5.TRADE_ACTION_DEAL,
    "symbol": "{cfg['symbol']}",
    "volume": {lot},
    "type": mt5.ORDER_TYPE_BUY if {direction} == 0 else mt5.ORDER_TYPE_SELL,
    "price": mt5.symbol_info_tick("{cfg['symbol']}").ask if {direction} == 0 else mt5.symbol_info_tick("{cfg['symbol']}").bid,
    "sl": {decision.get('sl') or 0.0},
    "tp": {decision.get('tp') or 0.0},
    "deviation": {cfg['execution']['deviation_points']},
    "magic": {cfg['execution']['magic']},
    "comment": "{cfg['execution']['comment']}",
    "type_time": mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_IOC,
}}
result = mt5.order_send(request)
if result is None:
    print(json.dumps({{"ok": False, "error": "order_send None:" + str(mt5.last_error())}}))
elif result.retcode != mt5.TRADE_RETCODE_DONE:
    print(json.dumps({{"ok": False, "error": "retcode %s: %s" % (result.retcode, result.comment)}}))
else:
    pos = mt5.positions_get(ticket=result.order)
    print(json.dumps({{"ok": True, "ticket": result.order, "deal": result.deal,
                       "volume": result.volume, "price": result.price,
                       "pos_open": (pos[0].price_open if pos else None)}}))
mt5.shutdown()
"""


def _execute_live(cfg: dict, decision: dict, lot: float) -> dict:
    wp = _wine_python(cfg)
    if not os.path.exists(wp):
        log.warn("No Wine-Python in bottle — falling back to paper execution.")
        return _execute_paper(cfg, decision, lot, reason="wine-python missing")

    wine = shutil.which("wine")
    if not wine:
        wine = os.path.join(os.path.expanduser("~/.local/share/bottles/runners"),
                            cfg["bottle"]["runner"], "bin", "wine")

    script = _build_order_script(cfg, decision, lot)
    script_path = os.path.join(os.path.expanduser(cfg["bottle"]["prefix"]),
                               "drive_c", "Python310", "_ur_order.py")
    with open(script_path, "w") as f:
        f.write(script)

    env = dict(os.environ)
    env["WINEPREFIX"] = os.path.expanduser(cfg["bottle"]["prefix"])
    env.setdefault("DISPLAY", os.environ.get("DISPLAY") or ":0")
    env["WINEDEBUG"] = "-all"

    try:
        proc = subprocess.run(
            [wine, os.path.join(os.path.expanduser(cfg["bottle"]["prefix"]),
                                "drive_c", "Python310", "python.exe"), script_path],
            capture_output=True, text=True, timeout=90, env=env,
        )
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        log.warn(f"Live execution produced no JSON output: {proc.stdout[-200:]}")
        return {"ok": False, "error": "no-json-output"}
    except Exception as e:
        return {"ok": False, "error": f"wine exec error: {e}"}


def _execute_paper(cfg: dict, decision: dict, lot: float, reason: str = "") -> dict:
    rec = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": cfg["symbol"],
        "direction": decision["direction"],
        "lot": lot,
        "entry": decision.get("entry"),
        "sl": decision.get("sl"),
        "tp": decision.get("tp"),
        "reason": reason or "paper mode",
    }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "paper_trades.json")
    path = os.path.abspath(path)
    records = []
    if os.path.exists(path):
        try:
            records = json.load(open(path))
        except Exception:
            records = []
    records.append(rec)
    with open(path, "w") as f:
        json.dump(records, f, indent=2)
    log.warn(f"PAPER FILL: {rec['direction']} {rec['lot']} {rec['symbol']} @ {rec['entry']} "
             f"(SL {rec['sl']}, TP {rec['tp']}) — {rec['reason']}")
    log.warn(f"Recorded in {path}")
    return {"ok": True, "paper": True, **rec}


def execute(cfg: dict, decision: dict) -> dict:
    price = decision.get("price") or decision.get("entry")
    lot = decision.get("lot") or _lot(cfg, price or 1.0, decision.get("sl") or (price or 1.0) * 0.999)
    decision["lot"] = lot

    if cfg["execution"]["mode"] == "paper":
        return _execute_paper(cfg, decision, lot, reason="paper mode")

    result = _execute_live(cfg, decision, lot)
    if result.get("ok"):
        log.ok(f"LIVE ORDER FILLED: ticket={result.get('ticket')} "
               f"deal={result.get('deal')} vol={result.get('volume')} @ {result.get('price')}")
        return result
    log.warn(f"Live execution failed ({result.get('error')}) — recording paper fill instead.")
    return _execute_paper(cfg, decision, lot, reason=str(result.get("error"))[:80])
