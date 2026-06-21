from datetime import datetime
from loguru import logger
from macro.fred import fetch_fred_data
from macro.live import fetch_live_data
from macro.treasury import fetch_treasury_data
from notifications.telegram import send_message
from state import load_state, save_state

SERIES_META = {
    "vix":              {"label": "VIX",        "unit": ""},
    "move":             {"label": "MOVE",       "unit": ""},
    "skew":             {"label": "SKEW",       "unit": ""},
    "us10y":            {"label": "10Y Yield",  "unit": "%"},
    "hy_spread":        {"label": "HY Spread",  "unit": " bps"},
    "ig_spread":        {"label": "IG Spread",  "unit": " bps"},
    "cpi":              {"label": "CPI",        "unit": "%"},
    "core_cpi":         {"label": "Core CPI",   "unit": "%"},
    "sofr":             {"label": "SOFR",       "unit": "%"},
    "effr":             {"label": "EFFR",       "unit": "%"},
    "sofr_effr_spread": {"label": "SOFR-EFFR",  "unit": "%"},
    "repo":             {"label": "Repo",       "unit": " B"},
    "rrp":              {"label": "RRP",        "unit": " B"},
    "tga":              {"label": "TGA",        "unit": " B"},
}


def _fmt_date(iso: str) -> str:
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d %b")
    except ValueError:
        return iso


def _fmt_line(key: str, entry: dict, is_new: bool) -> str:
    meta = SERIES_META.get(key, {"label": key, "unit": ""})
    marker = "+" if is_new else "."
    date = f"{_fmt_date(entry['date']):<7}"
    label = f"{meta['label']:<14}"
    value = f"{entry['value']}{meta['unit']}"
    return f"`[{marker}] {date}  {label}{value}`"


def _value_changed(state_entry, new_value) -> bool:
    if not isinstance(state_entry, dict):
        return False  # legacy or missing: no prior value to compare
    return state_entry.get("value") != new_value


def _first_seen(state_entry) -> bool:
    return state_entry is None  # never tracked before (legacy strings don't count)


def _persist(state: dict, all_data: dict) -> None:
    for key, entry in all_data.items():
        state[key] = {"date": entry["date"], "value": entry["value"]}
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

    # Notify purely on value movement, never on the release date. A changed
    # value is newsworthy even within the same day; an unchanged value is not,
    # no matter how many days (or new release dates) have passed.
    value_changed_keys = {k for k, v in all_data.items()
                          if _value_changed(state.get(k), v["value"])}

    # First sighting of a series establishes its baseline and is worth one
    # notification; legacy date-only state entries are baselined silently.
    notify_keys = value_changed_keys | {k for k in all_data if _first_seen(state.get(k))}

    if not notify_keys:
        logger.info("No value changes; nothing to notify.")
        _persist(state, all_data)
        return

    today = datetime.now().strftime("%d %b %Y")
    lines = [f"*Macro Update — {len(notify_keys)} update(s)*  |  {today}"]
    lines.append("")
    for key in SERIES_META:
        entry = all_data.get(key)
        if entry is None:
            continue
        lines.append(_fmt_line(key, entry, is_new=(key in value_changed_keys)))

    send_message("\n".join(lines))

    for key in notify_keys:
        logger.info(f"Update: {SERIES_META.get(key, {}).get('label', key)} ({all_data[key]['date']})")

    _persist(state, all_data)
    logger.info(f"Notified {len(notify_keys)} update(s).")
