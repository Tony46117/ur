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


def _mt5_creds(cfg: dict):
    """MT5 auto-login credentials from config `mt5:` section or apis.txt keys.

    Returns (login, password, server) — empty strings when not configured.
    Preference: config.yaml mt5: block, then _keys (mt5_login / mt5_password /
    mt5_server in apis.txt).
    """
    m = cfg.get("mt5") or {}
    keys = cfg.get("_keys") or {}
    login = str(m.get("login") or keys.get("mt5_login") or "").strip()
    password = str(m.get("password") or keys.get("mt5_password") or "").strip()
    server = str(m.get("server") or keys.get("mt5_server") or "").strip()
    return login, password, server


def _init_call(login: str, password: str, server: str) -> str:
    """Build the mt5.initialize(...) Python snippet, with auto-login when set."""
    if login:
        # escape for embedding inside the generated script
        l, p, s = json.dumps(login), json.dumps(password), json.dumps(server)
        return f"mt5.initialize(login={l}, password={p}, server={s})"
    return "mt5.initialize()"


def _build_order_script(cfg: dict, decision: dict, lot: float) -> str:
    direction = 0 if decision["direction"] == "BUY" else 1  # POSITION_TYPE_BUY/SELL
    login, password, server = _mt5_creds(cfg)
    init = _init_call(login, password, server)
    if login:
        init_extra = f"# auto-login configured for account {json.dumps(login)}"
    else:
        init_extra = "# no auto-login configured — using the account logged in the terminal"
    return f"""
import json, sys
import MetaTrader5 as mt5

{init_extra}
ok = {init}
if not ok:
    print(json.dumps({{"ok": False, "error": "init:" + str(mt5.last_error())}}))
    sys.exit(0)

info = mt5.account_info()
if info is None:
    print(json.dumps({{"ok": False, "error": "no-account:" + str(mt5.last_error())}}))
    mt5.shutdown(); sys.exit(0)

# ── SAFETY: only ever trade demo/paper accounts, never live money ──
try:
    server = (info.server or "").lower()
    trade_mode = int(getattr(info, "trade_mode", -1))
except Exception:
    server, trade_mode = "", -1
# ACCOUNT_TRADE_MODE_DEMO == 0, ACCOUNT_TRADE_MODE_CONTEST == 1,
# ACCOUNT_TRADE_MODE_REAL == 2 — refuse real-money accounts outright
if trade_mode == 2 or (trade_mode not in (0, 1) and "demo" not in server):
    print(json.dumps({{"ok": False, "error": "refusing-non-demo-account "
                       "(server='%s' mode=%s)" % (info.server, trade_mode)}}))
    mt5.shutdown(); sys.exit(0)

tick = mt5.symbol_info_tick("{cfg['symbol']}")
if tick is None:
    print(json.dumps({{"ok": False, "error": "no-tick-for-symbol"}}))
    mt5.shutdown(); sys.exit(0)

request = {{
    "action": mt5.TRADE_ACTION_DEAL,
    "symbol": "{cfg['symbol']}",
    "volume": {lot},
    "type": mt5.ORDER_TYPE_BUY if {direction} == 0 else mt5.ORDER_TYPE_SELL,
    "price": tick.ask if {direction} == 0 else tick.bid,
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


def _run_wine_script(cfg: dict, script_name: str, script: str, timeout: int = 90) -> dict:
    """Run a generated Python script inside the bottle's Wine-Python and return
    the first JSON object it prints. The script is deleted afterwards so the
    (possibly credential-bearing) helper never lingers on disk.

    Returns {"ok": False, "error": ...} on any failure.
    """
    wp = _wine_python(cfg)
    if not os.path.exists(wp):
        return {"ok": False, "error": "wine-python missing"}

    wine = shutil.which("wine")
    if not wine:
        wine = os.path.join(os.path.expanduser("~/.local/share/bottles/runners"),
                            cfg["bottle"]["runner"], "bin", "wine")

    prefix = os.path.expanduser(cfg["bottle"]["prefix"])
    script_path = os.path.join(prefix, "drive_c", "Python310", script_name)
    env = dict(os.environ)
    env["WINEPREFIX"] = prefix
    env.setdefault("DISPLAY", os.environ.get("DISPLAY") or ":0")
    env["WINEDEBUG"] = "-all"

    try:
        with open(script_path, "w") as f:
            f.write(script)
        proc = subprocess.run(
            [wine, os.path.join(prefix, "drive_c", "Python310", "python.exe"), script_path],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        return {"ok": False, "error": f"no-json-output: {(proc.stdout or '')[-200:]}"}
    except Exception as e:
        return {"ok": False, "error": f"wine exec error: {e}"}
    finally:
        try:
            if os.path.exists(script_path):
                os.remove(script_path)
        except OSError:
            pass


def _execute_live(cfg: dict, decision: dict, lot: float) -> dict:
    script = _build_order_script(cfg, decision, lot)
    return _run_wine_script(cfg, "_ur_order.py", script)


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
    # atomic write: never leave a truncated/corrupt paper_trades.json behind
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(records, f, indent=2)
    os.replace(tmp, path)
    log.warn(f"PAPER FILL: {rec['direction']} {rec['lot']} {rec['symbol']} @ {rec['entry']} "
             f"(SL {rec['sl']}, TP {rec['tp']}) — {rec['reason']}")
    log.warn(f"Recorded in {path}")
    return {"ok": True, "paper": True, **rec}


def check_connection(cfg: dict) -> dict:
    """Diagnostic (--check): verify the MT5 terminal is reachable, report the
    connected account (login/server/mode/balance) without placing any order.

    Returns a dict: {ok, connected, build, account: {...} | None, error}.
    """
    wp = _wine_python(cfg)
    if not os.path.exists(wp):
        log.err(f"No Wine-Python at {wp} — install Python 3.10 + MetaTrader5 in the bottle.")
        return {"ok": False, "error": "wine-python missing"}

    wine = shutil.which("wine")
    if not wine:
        wine = os.path.join(os.path.expanduser("~/.local/share/bottles/runners"),
                            cfg["bottle"]["runner"], "bin", "wine")

    login, password, server = _mt5_creds(cfg)
    init = _init_call(login, password, server)
    script = f"""
import json, sys
import MetaTrader5 as mt5
ok = {init}
if not ok:
    print(json.dumps({{"ok": False, "error": "init:" + str(mt5.last_error())}}))
    sys.exit(0)
ti = mt5.terminal_info()
ai = mt5.account_info()
out = {{"ok": True, "connected": bool(ti and ti.connected), "build": (ti.build if ti else None)}}
if ai is None:
    out["account"] = None
    out["error"] = "terminal reachable but no account logged in: " + str(mt5.last_error())
else:
    out["account"] = {{"login": ai.login, "server": ai.server, "trade_mode": int(ai.trade_mode),
                        "balance": ai.balance, "equity": ai.equity, "currency": ai.currency,
                        "leverage": ai.leverage}}
print(json.dumps(out))
mt5.shutdown()
"""
    return _run_wine_script(cfg, "_ur_check.py", script)


def execute(cfg: dict, decision: dict) -> dict:
    price = decision.get("price") or decision.get("entry")
    lot = decision.get("lot") or _lot(cfg, price or 1.0, decision.get("sl") or (price or 1.0) * 0.999)
    decision["lot"] = lot

    if cfg["execution"]["mode"] == "paper":
        return _execute_paper(cfg, decision, lot, reason="paper mode")

    result = _execute_live(cfg, decision, lot)
    if result.get("ok"):
        if result.get("paper"):
            return result  # already a paper fill (reason set internally)
        log.ok(f"LIVE ORDER FILLED: ticket={result.get('ticket')} "
               f"deal={result.get('deal')} vol={result.get('volume')} @ {result.get('price')}")
        return result
    log.warn(f"Live execution failed ({result.get('error')}) — recording paper fill instead.")
    return _execute_paper(cfg, decision, lot, reason=str(result.get("error"))[:80])
