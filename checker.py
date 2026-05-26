from datetime import datetime
from loguru import logger
from macro.fred import fetch_fred_data
from macro.live import fetch_live_data
from notifications.telegram import send_message
from state import load_state, save_state

SERIES_META = {
    "fed_funds_rate":        {"label": "Fed Funds Rate", "unit": "%"},
    "fed_funds_target_upper":{"label": "Target Hi",      "unit": "%"},
    "fed_funds_target_lower":{"label": "Target Lo",      "unit": "%"},
    "ten_year_yield":        {"label": "10Y Yield",      "unit": "%"},
    "real_10y":              {"label": "Real 10Y",       "unit": "%"},
    "yield_curve":           {"label": "Yield Curve",    "unit": "%"},
    "cpi":                   {"label": "CPI",            "unit": ""},
    "core_cpi":              {"label": "Core CPI",       "unit": ""},
    "unemployment_rate":     {"label": "Unemploy",       "unit": "%"},
    "hy_spread":             {"label": "HY Spread",      "unit": " bps"},
    "vix":                   {"label": "VIX",            "unit": ""},
    "skew":                  {"label": "SKEW",           "unit": ""},
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
    yoy = f"  {entry['yoy']:+.1f}%y" if "yoy" in entry else ""
    return f"`[{marker}] {date}  {label}{value}{yoy}`"


def run_check() -> None:
    logger.info("Checking macro data for new releases...")
    state = load_state()

    all_data: dict = {}
    all_data.update(fetch_fred_data())
    all_data.update(fetch_live_data())

    new_keys = {k for k, v in all_data.items() if v.get("date") and state.get(k) != v["date"]}

    if not new_keys:
        logger.info("No new releases.")
        return

    today = datetime.now().strftime("%d %b %Y")
    lines = [f"*Macro Update — {len(new_keys)} new release(s)*  |  {today}"]
    lines.append("")
    for key in SERIES_META:
        entry = all_data.get(key)
        if entry is None:
            continue
        lines.append(_fmt_line(key, entry, is_new=(key in new_keys)))

    send_message("\n".join(lines))

    for key in new_keys:
        state[key] = all_data[key]["date"]
        logger.info(f"New: {SERIES_META.get(key, {}).get('label', key)} ({all_data[key]['date']})")

    save_state(state)
    logger.info(f"Notified {len(new_keys)} new release(s).")
