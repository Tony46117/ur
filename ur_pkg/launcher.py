"""Launcher — ensures the MT5 terminal is running via the Bottles 'mt5' bottle."""
import os
import re
import shutil
import subprocess
import time
from ur_pkg.log import Log

log = Log.get("ur")


def _is_terminal_running() -> bool:
    try:
        out = subprocess.run(["pgrep", "-af", "terminal64"], capture_output=True, text=True, timeout=10)
        return "terminal64" in out.stdout
    except Exception:
        return False


def _detect_build(prefix: str) -> str:
    """Read the newest terminal log (UTF-16) and extract the build number."""
    logs_dir = os.path.join(prefix, "drive_c", "Program Files", "MetaTrader 5", "logs")
    if not os.path.isdir(logs_dir):
        return ""
    try:
        logs = sorted(
            (os.path.join(logs_dir, f) for f in os.listdir(logs_dir) if f.endswith(".log")),
            key=os.path.getmtime, reverse=True,
        )
        for lp in logs[:3]:
            with open(lp, "rb") as fh:
                raw = fh.read(200_000)
            text = raw.decode("utf-16-le", errors="ignore")
            m = re.search(r"MetaTrader 5 x64 build (\d+)", text)
            if m:
                return m.group(1)
            m2 = re.search(r"build (\d+)", text)
            if m2:
                return m2.group(1)
    except Exception:
        pass
    return ""


def ensure_terminal(cfg: dict) -> dict:
    """Launch the MT5 terminal from the Bottles bottle if not already running."""
    state = "already-running"
    if _is_terminal_running():
        log.info("MT5 terminal process already running.")
    else:
        if not cfg["execution"]["launch"]:
            state = "not-running"
            log.warn("MT5 terminal not running and launch disabled (--no-launch).")
        else:
            state = _launch_via_bottles(cfg)

    time.sleep(2)
    return {
        "state": state,
        "running": _is_terminal_running(),
        "build": _detect_build(cfg["bottle"]["prefix"]),
    }


def _launch_via_bottles(cfg: dict) -> str:
    """Launch terminal64.exe inside the 'mt5' bottle using bottles-cli."""
    bottle = cfg["bottle"]["name"]
    exe = cfg["bottle"]["terminal_path"]

    bottles_cli = shutil.which("bottles-cli")
    if not bottles_cli:
        log.err("bottles-cli not found — cannot launch the mt5 bottle.")
        return "launch-failed"

    cmd = [bottles_cli, "run", "-b", bottle, "-e", exe, "/portable"]
    log.info(f"Launching MT5 via bottles-cli: {' '.join(cmd)}")
    try:
        env = dict(os.environ)
        env.setdefault("DISPLAY", os.environ.get("DISPLAY") or ":0")
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env, start_new_session=True,
        )
        # wait up to 60s for the terminal process to appear
        for _ in range(60):
            time.sleep(1)
            if _is_terminal_running():
                log.ok("MT5 terminal process detected.")
                return "launched"
        log.warn("Timed out waiting for terminal64 process (check the Bottles window).")
        return "launched-uncertain"
    except Exception as e:
        log.err(f"bottles-cli launch error: {e}")
        return "launch-failed"
