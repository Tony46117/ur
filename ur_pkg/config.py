"""Configuration loader: config.yaml + keys file (apis.txt)."""
import os
import re
import yaml


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # expand ~ in paths
    for key in ("prefix", "keys_file"):
        val = cfg.get("bottle", {}).get(key) if key == "prefix" else cfg.get(key)
        if isinstance(val, str) and val.startswith("~"):
            (cfg["bottle"] if key == "prefix" else cfg).update({key: os.path.expanduser(val)})

    cfg["_keys"] = load_keys(cfg.get("keys_file"))
    return cfg


def load_keys(path: str) -> dict:
    """Parse KEY = VALUE lines from apis.txt. Returns dict; never logs values."""
    keys = {}
    if not path or not os.path.exists(path):
        return keys
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(r"^([A-Za-z0-9 _\-]+?)\s*[=:]\s*(\S+)\s*$", line)
                if m:
                    k = m.group(1).strip().lower().replace(" ", "_")
                    keys[k] = m.group(2).strip()
    except Exception:
        pass
    return keys
