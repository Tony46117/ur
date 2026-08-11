"""Architecture diagram generator — produces an SVG saved to ~/Documents."""
import os
from ur_pkg.log import Log

log = Log.get("ur")


def generate_architecture_diagram(cfg: dict, out_path: str = None) -> str:
    if out_path is None:
        out_path = os.path.expanduser("~/Documents/ur_architecture.svg")

    # (x, y, w, h, title, subtitle, color)
    boxes = [
        (40, 40, 300, 90, "ur.py", "entry point — python3 ur.py", "#1f6feb"),
        (40, 180, 300, 220, "LAUNCHER", "Bottles (bottles-cli)\nlaunch mt5 bottle\nMT5 terminal (Wine)", "#8957e5"),
        (420, 40, 280, 100, "DATA COLLECTORS", "parallel threads · 45s timeout", "#238636"),
        (420, 170, 280, 420, "LIVE DATA SOURCES", "", "#1f6feb"),
        (780, 40, 300, 100, "FUSION ENGINE", "weighted scores → verdict", "#d29922"),
        (780, 180, 300, 140, "RISK MANAGER", "ATR-based SL/TP\nlot sizing (1% risk)", "#8957e5"),
        (780, 360, 300, 120, "EXECUTOR", "MetaTrader5 order_send\n→ paper fallback", "#d29922"),
        (420, 640, 300, 80, "MT5 TERMINAL", "demo account · live order", "#238636"),
    ]
    lines = [
        (40, 130, 40, 180),                  # ur.py → launcher
        (220, 130, 560, 40),                 # ur.py → collectors
        (560, 140, 560, 170),                # collectors → sources
        (700, 250, 780, 90),                 # sources → fusion
        (930, 140, 930, 180),                # fusion → risk
        (930, 320, 930, 360),                # risk → executor
        (620, 590, 620, 640),                # executor → mt5
        (220, 400, 420, 90),                 # launcher → mt5 (implied)
    ]

    w, h = 1120, 760
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
           f'viewBox="0 0 {w} {h}" font-family="Segoe UI, sans-serif">']
    svg.append(f'<rect width="{w}" height="{h}" fill="#0d1117"/>')
    svg.append(f'<text x="40" y="28" fill="#e6edf3" font-size="20" font-weight="700">'
               f'ur — Autonomous EURUSD Trading Software · Architecture</text>')

    for x, y, bw, bh, title, sub, color in boxes:
        svg.append(f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="10" '
                   f'fill="{color}" fill-opacity="0.15" stroke="{color}" stroke-width="2"/>')
        svg.append(f'<text x="{x + 14}" y="{y + 28}" fill="#e6edf3" font-size="15" '
                   f'font-weight="700">{title}</text>')
        for i, ln in enumerate(sub.split("\n")):
            svg.append(f'<text x="{x + 14}" y="{y + 50 + i * 20}" fill="#9da7b3" '
                       f'font-size="12">{ln}</text>')

    for x1, y1, x2, y2 in lines:
        svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#58a6ff" '
                   f'stroke-width="2" marker-end="url(#arrow)"/>')

    svg.append('<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" '
               'orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#58a6ff"/></marker></defs>')

    # legend for data sources
    lx, ly = 436, 200
    sources = [
        "Forex Factory — economic calendar (live scrape / CSV fallback)",
        "TradingView — TA widget summary (oscillators + MAs)",
        "Yahoo Finance — live spot EURUSD, DXY, VIX, US10Y",
        "CFTC COT API — Euro FX open interest & positioning",
        "CME options flow — proxied via COT (DataCloud if subscribed)",
    ]
    for i, s in enumerate(sources):
        svg.append(f'<text x="{lx}" y="{ly + i * 24}" fill="#9da7b3" font-size="12.5">• {s}</text>')

    svg.append('</svg>')

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write("\n".join(svg))
    return out_path
