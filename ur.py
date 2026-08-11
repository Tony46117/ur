#!/usr/bin/env python3
"""
ur — autonomous EURUSD trading software.

Run:  python3 ur.py
Flow: launch MT5 (Bottles) → collect live data (Forex Factory, TradingView,
CFTC/COT + options flow, cross-asset) → fuse signals → decide → execute
into the running MT5 terminal (paper fallback if the terminal can't attach).

Flags:
  --symbol EURUSD      pair to trade (default from config)
  --lot 0.47           fixed lot size (overrides risk-based sizing)
  --paper              force paper execution (no real order)
  --dry-run            analyze only; print decision, do NOT execute
  --diagram            generate architecture diagram and exit
  --no-launch          do not try to launch the MT5 terminal
  --verbose            debug logging
"""

import argparse
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from ur_pkg.log import Log
from ur_pkg.config import load_config


def main() -> int:
    ap = argparse.ArgumentParser(description="ur — autonomous EURUSD trader")
    ap.add_argument("--symbol", default=None)
    ap.add_argument("--lot", type=float, default=None)
    ap.add_argument("--paper", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--diagram", action="store_true")
    ap.add_argument("--no-launch", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    cfg = load_config(os.path.join(BASE_DIR, "config.yaml"))
    if args.symbol:
        cfg["symbol"] = args.symbol.upper()
    if args.lot:
        cfg["lot_override"] = args.lot
    if args.paper:
        cfg["execution"]["mode"] = "paper"
    if args.dry_run:
        cfg["execution"]["mode"] = "dry"
    cfg["execution"]["launch"] = not args.no_launch

    Log.setup(verbose=args.verbose, log_dir=os.path.join(BASE_DIR, "logs"))
    log = Log.get("ur")

    log.banner()
    log.info(f"BASE_DIR : {BASE_DIR}")
    log.info(f"SYMBOL   : {cfg['symbol']}   MODE: {cfg['execution']['mode']}")

    # ── 1. Architecture diagram (optional) ────────────────────────
    if args.diagram:
        from ur_pkg.arch import generate_architecture_diagram
        path = generate_architecture_diagram(cfg)
        log.ok(f"Architecture diagram saved -> {path}")
        return 0

    # ── 2. Launch MT5 terminal via Bottles ────────────────────────
    from ur_pkg.launcher import ensure_terminal
    terminal = ensure_terminal(cfg)
    log.ok(f"MT5 terminal: {terminal['state']} (build {terminal.get('build') or '?'})")

    # ── 3. Collect live market data ───────────────────────────────
    from ur_pkg.collector import collect_all
    data = collect_all(cfg)
    log.info(f"Data: spot={data['spot'].get('source')} tv={data['tv'].get('available')} "
             f"tech={data['technical'].get('available')} "
             f"news_events={data['news'].get('events_analyzed')} "
             f"cot={data['cme'].get('available')} cross={data['cross'].get('available')}")

    # ── 4. Decide ─────────────────────────────────────────────────
    from ur_pkg.signals.fusion import decide
    from ur_pkg.signals.llm import overlay as llm_overlay
    decision = decide(cfg, data)
    decision = llm_overlay(cfg, data, decision)
    log.line()
    log.info(f"DECISION: {decision['direction']}  score={decision['score']}  "
             f"conviction={decision['conviction']}  agreement={decision['agreement']}")
    log.info(f"VERDICT : {decision['verdict']}")
    log.info(f"ENTRY   : {decision['entry']}   SL: {decision['sl']}   "
             f"TP: {decision['tp']}   RR: {decision['rr']}")

    # ── 5. Execute ────────────────────────────────────────────────
    if cfg["execution"]["mode"] == "dry":
        log.warn("DRY-RUN: no order placed.")
        decision["paper"] = True
    elif decision["direction"] == "HOLD":
        log.warn("HOLD — no trade taken.")
    else:
        from ur_pkg.trading.executor import execute
        result = execute(cfg, decision)
        decision["execution"] = result

    log.line()
    log.ok("ur run complete.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
