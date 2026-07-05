from datetime import datetime
from loguru import logger
from macro.fred import fetch_fred_data
from macro.live import fetch_live_data
from macro.treasury import fetch_treasury_data
from notifications.telegram import send_message
from state import load_state, save_state
from agent.claude_client import analyze_macro_data

SERIES_META = {
    "vix":              {"label": "VIX",        "unit": ""},
    "move":             {"label": "MOVE",       "unit": ""},
    "skew":             {"label": "SKEW",       "unit": ""},
    "us10y":            {"label": "10Y Yield",  "unit": "%"},
    "hy_spread":        {"label": "HY Spread",  "unit": " bps"},
    "ccc_spread":       {"label": "CCC Spread", "unit": " bps"},
    "ig_spread":        {"label": "IG Spread",  "unit": " bps"},
    "cpi":              {"label": "CPI",        "unit": "%"},
    "core_cpi":         {"label": "Core CPI",   "unit": "%"},
    "sofr":             {"label": "SOFR",       "unit": "%"},
    "effr":             {"label": "EFFR",       "unit": "%"},
    "sofr_effr_spread": {"label": "SOFR-EFFR",  "unit": "%"},
    "walcl":            {"label": "WALCL",      "unit": " B"},
    "rrp":              {"label": "RRP",        "unit": " B"},
    "tga":              {"label": "TGA",        "unit": " B"},
    "fed_net_liquidity":{"label": "Net Liq",    "unit": " B"},
}


def _fmt_date(iso: str) -> str:
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d %b")
    except ValueError:
        return iso[:10]


def _fmt_line(key: str, entry: dict, is_new: bool, history: list) -> str:
    meta = SERIES_META.get(key, {"label": key, "unit": ""})
    marker = "+" if is_new else "."
    date = f"{_fmt_date(entry['date']):<7}"
    label = f"{meta['label']:<14}"
    
    current_val_str = f"{entry['value']}{meta['unit']}"
    trend_str = _get_trend_delta(history, entry['value'], meta['unit'])
    
    return f"`[{marker}] {date}  {label}{current_val_str}{trend_str}`"


THRESHOLDS = {
    "vix": 1.0,    # Notify if VIX changes by >= 1.0 points
}


def _value_changed(key: str, state_entry, new_value) -> bool:
    if not isinstance(state_entry, dict):
        return False  # legacy or missing: no prior value to compare
    
    # Compare against the last notified value to prevent drift.
    # Fallback to the standard 'value' for backward compatibility if it's missing.
    old_value = state_entry.get("notified_value", state_entry.get("value"))
    if old_value is None:
        return True
        
    threshold = THRESHOLDS.get(key, 0.0)
    if threshold == 0.0:
        return old_value != new_value
        
    return abs(new_value - old_value) >= threshold


def _get_trend_delta(history: list, current_val: float, unit: str, min_days: int = 40, max_days: int = 65) -> str:
    if not history:
        return ""
    now = datetime.now()
    best_h = None
    best_age = float("inf")
    for h in history:
        try:
            h_date = datetime.strptime(h["date"][:10], "%Y-%m-%d")
            age = (now - h_date).days
            if min_days <= age <= max_days:
                if age < best_age:
                    best_age = age
                    best_h = h
        except Exception:
            continue
            
    if best_h is None: 
        return ""
        
    delta = current_val - best_h["value"]
    if abs(delta) < 0.001:
        return ""
        
    sign = "+" if delta > 0 else ""
    return f" ({best_age}d: {sign}{delta:.2f}{unit})"


def _first_seen(state_entry) -> bool:
    return not isinstance(state_entry, dict)


def _persist(state: dict, all_data: dict, notify_keys: set) -> None:
    now = datetime.now()
    for key, entry in all_data.items():
        state_entry = state.get(key, {})
        history = state_entry.get("history", [])
        
        # append current entry if date not already latest in history, else update it
        if not history or history[-1]["date"] != entry["date"]:
            history.append({"date": entry["date"], "value": entry["value"]})
        else:
            history[-1]["value"] = entry["value"]
            
        # trim to 65 days buffer
        new_history = []
        for h in history:
            try:
                h_date = datetime.strptime(h["date"][:10], "%Y-%m-%d")
                if (now - h_date).days <= 65:
                    new_history.append(h)
            except Exception:
                pass  # discard malformed entries
        
        # If we sent a notification (or it's the first time), the new notified_value is the current value.
        # Otherwise, we carry over the previous notified_value to maintain the anchor for thresholds.
        if key in notify_keys or _first_seen(state.get(key)):
            notified_val = entry["value"]
            notified_date = entry["date"]
        else:
            notified_val = state_entry.get("notified_value", state_entry.get("value"))
            notified_date = state_entry.get("notified_date", state_entry.get("date"))
            
        state[key] = {
            "date": entry["date"],
            "value": entry["value"],
            "notified_date": notified_date,
            "notified_value": notified_val,
            "history": new_history
        }
    save_state(state)


def run_check() -> None:
    logger.info("Checking macro data for new releases...")
    state = load_state()

    all_data: dict = {}
    all_data.update(fetch_fred_data())
    all_data.update(fetch_live_data())
    all_data.update(fetch_treasury_data())

    if "sofr" in all_data and "effr" in all_data:
        all_data["sofr_effr_spread"] = {
            "value": round(all_data["sofr"]["value"] - all_data["effr"]["value"], 4),
            "date": all_data["sofr"]["date"],
        }

    if "walcl" in all_data and "rrp" in all_data and "tga" in all_data:
        all_data["fed_net_liquidity"] = {
            "value": round(all_data["walcl"]["value"] - all_data["rrp"]["value"] - all_data["tga"]["value"], 3),
            "date": all_data["walcl"]["date"],
        }

    # Notify purely on value movement, never on the release date. A changed
    # value is newsworthy even within the same day; an unchanged value is not,
    # no matter how many days (or new release dates) have passed.
    value_changed_keys = {k for k, v in all_data.items()
                          if _value_changed(k, state.get(k), v["value"])}

    # First sighting of a series establishes its baseline and is worth one
    # notification; legacy date-only state entries are baselined silently.
    notify_keys = value_changed_keys | {k for k in all_data if _first_seen(state.get(k))}

    if not notify_keys:
        logger.info("No value changes; nothing to notify.")
        _persist(state, all_data, notify_keys)
        return

    today = datetime.now().strftime("%d %b %Y")
    lines = [f"*Macro Update — {len(notify_keys)} update(s)*  |  {today}"]
    lines.append("")
    for key in SERIES_META:
        entry = all_data.get(key)
        if entry is None:
            continue
        history = state.get(key, {}).get("history", [])
        lines.append(_fmt_line(key, entry, is_new=(key in value_changed_keys), history=history))

    notification_text = "\n".join(lines)
    
    # Analyze data with AI
    ai_assessment = analyze_macro_data(notification_text, all_data)
    if ai_assessment:
        lines.append("\n*AI Regime / Idea* 🤖:")
        lines.append(f"_{ai_assessment}_")

    send_message("\n".join(lines))

    for key in notify_keys:
        logger.info(f"Update: {SERIES_META.get(key, {}).get('label', key)} ({all_data[key]['date']})")

    _persist(state, all_data, notify_keys)
    logger.info(f"Notified {len(notify_keys)} update(s).")
