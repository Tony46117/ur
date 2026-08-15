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


def _log_dirs(prefix: str):
    """All directories where MT5 may write its daily log (UTF-16)."""
    dirs = [os.path.join(prefix, "drive_c", "Program Files", "MetaTrader 5", "logs")]
    # portable mode logs live under AppData/Roaming/MetaQuotes/Terminal/<hash>/
    terminal = os.path.join(prefix, "drive_c", "users", "steamuser",
                            "AppData", "Roaming", "MetaQuotes", "Terminal")
    if os.path.isdir(terminal):
        for name in os.listdir(terminal):
            for sub in ("logs", os.path.join("temp", "logs")):
                d = os.path.join(terminal, name, sub)
                if os.path.isdir(d):
                    dirs.append(d)
    return dirs


def _newest_logs(prefix: str, limit: int = 6):
    logs = []
    for d in _log_dirs(prefix):
        try:
            logs += [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".log")]
        except OSError:
            continue
    logs.sort(key=os.path.getmtime, reverse=True)
    return logs[:limit]


def _detect_build(prefix: str) -> str:
    """Read the newest terminal logs (UTF-16) and extract the LATEST build number.

    A daily log contains every session of the day ("build 5977 started",
    "build 6104 started"...) — we want the last one, not the first.
    """
    for lp in _newest_logs(prefix):
        try:
            with open(lp, "rb") as fh:
                raw = fh.read(300_000)
            text = raw.decode("utf-16-le", errors="ignore")
            builds = re.findall(r"MetaTrader 5 x64 build (\d+)", text)
            if builds:
                return builds[-1]
            builds = re.findall(r"build (\d+)", text)
            if builds:
                return builds[-1]
        except Exception:
            continue
    return ""


def _latest_auth_error(prefix: str) -> str:
    """Return the most recent account authorization failure from the logs
    (e.g. "'108775433': authorization on MetaQuotes-Demo failed (Invalid
    account)") — the usual reason live orders silently fall back to paper."""
    for lp in _newest_logs(prefix, limit=4):
        try:
            with open(lp, "rb") as fh:
                raw = fh.read(300_000)
            text = raw.decode("utf-16-le", errors="ignore")
            # logs are chronological — take the LAST failure, not the first
            fails = re.findall(r"authorization on [^ ]+ failed \(([^)]+)\)", text)
            if fails:
                return fails[-1]
        except Exception:
            continue
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
    prefix = cfg["bottle"]["prefix"]
    auth_err = _latest_auth_error(prefix)
    if auth_err:
        log.warn(f"MT5 account authorization failed ({auth_err}) — live orders will "
                 f"fall back to paper. Set mt5.login/password/server in config.yaml "
                 f"or apis.txt, or log in inside the terminal.")
    return {
        "state": state,
        "running": _is_terminal_running(),
        "build": _detect_build(prefix),
        "auth_error": auth_err,
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
