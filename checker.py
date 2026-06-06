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
    "dxy":              {"label": "DXY",        "unit": ""},
    "usdjpy":           {"label": "USD/JPY",    "unit": ""},
    "us10y":            {"label": "10Y Yield",  "unit": "%"},
    "hy_spread":        {"label": "HY Spread",  "unit": " bps"},
    "ig_spread":        {"label": "IG Spread",  "unit": " bps"},
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


def _state_date(entry) -> str | None:
    if isinstance(entry, dict):
        return entry.get("date")
    return entry  # legacy: plain date string


def _value_changed(state_entry, new_value) -> bool:
    if not isinstance(state_entry, dict):
        return False  # legacy or missing: no prior value to compare
    return state_entry.get("value") != new_value


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

    new_keys = {k for k, v in all_data.items()
                if v.get("date") and _state_date(state.get(k)) != v["date"]}

    if not new_keys:
        logger.info("No new releases.")
        return

    value_changed_keys = {k for k in new_keys
                          if _value_changed(state.get(k), all_data[k]["value"])}

    today = datetime.now().strftime("%d %b %Y")
    lines = [f"*Macro Update — {len(new_keys)} new release(s)*  |  {today}"]
    lines.append("")
    for key in SERIES_META:
        entry = all_data.get(key)
        if entry is None:
            continue
        lines.append(_fmt_line(key, entry, is_new=(key in value_changed_keys)))

    send_message("\n".join(lines))

    for key in new_keys:
        state[key] = {"date": all_data[key]["date"], "value": all_data[key]["value"]}
        logger.info(f"New: {SERIES_META.get(key, {}).get('label', key)} ({all_data[key]['date']})")

    save_state(state)
    logger.info(f"Notified {len(new_keys)} new release(s).")
