"""LLM decision overlay — optional second opinion on the fused decision.

Uses the `deepseek` key from apis.txt (loaded by config, never logged).
If the key is missing, the API fails, or the LLM agrees, the numeric
decision stands unchanged. Only a strong LLM disagreement with a
non-HOLD decision downgrades conviction by one level.

Set `llm.enabled: false` in config.yaml to disable entirely.
"""
import requests
from ur_pkg.log import Log

log = Log.get("ur")


def _build_prompt(cfg, data, decision) -> str:
    comps = decision.get("components", {})
    lines = [f"Forex decision assistant for {cfg['symbol']}.",
             "You get component scores (0=strong sell, 100=strong buy):"]
    for k, v in comps.items():
        lines.append(f"- {k}: {v}")
    price = decision.get("price")
    if price:
        lines.append(f"Current spot: {price}")
    lines.append("Answer EXACTLY one line: BUY, SELL, or HOLD. Then one short reason line.")
    return "\n".join(lines)


def overlay(cfg: dict, data: dict, decision: dict) -> dict:
    decision = dict(decision)
    llm_cfg = cfg.get("llm", {})
    if not llm_cfg.get("enabled"):
        return decision

    key = cfg.get("_keys", {}).get("deepseek")
    if not key:
        return decision

    try:
        r = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={
                "model": llm_cfg.get("model", "deepseek-chat"),
                "messages": [
                    {"role": "system", "content": "You are a terse forex risk assistant."},
                    {"role": "user", "content": _build_prompt(cfg, data, decision)},
                ],
                "max_tokens": 60,
                "temperature": 0.2,
            },
            timeout=llm_cfg.get("timeout", 25),
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.debug(f"LLM overlay skipped: {e}")
        return decision

    llm_dir = "HOLD"
    for token in ("BUY", "SELL", "HOLD"):
        if token in content.upper()[:12]:
            llm_dir = token
            break
    decision["llm"] = {"direction": llm_dir, "raw": content[:160]}

    # strong disagreement on an actionable trade → downgrade conviction
    if decision["direction"] in ("BUY", "SELL") and llm_dir == "HOLD":
        if decision["conviction"] == "HIGH":
            decision["conviction"] = "MEDIUM"
        elif decision["conviction"] == "MEDIUM":
            decision["conviction"] = "LOW"
        decision["verdict"] += "  [LLM: HOLD — vetoed]"
    elif decision["direction"] == "HOLD" and llm_dir in ("BUY", "SELL"):
        decision["conviction"] = "LOW"
        decision["verdict"] += f"  [LLM: {llm_dir} — awaiting confluence]"

    return decision
