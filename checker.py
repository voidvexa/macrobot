from loguru import logger
from macro.fred import fetch_fred_data
from macro.live import fetch_live_data
from macro.treasury import fetch_treasury_data
from db import (
    get_series_metadata,
    get_latest_observations,
    insert_observation,
    update_observation,
)


def run_check() -> None:
    logger.info("Checking macro data for new observations...")
    series_meta = get_series_metadata()
    latest_obs = get_latest_observations()

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

    new_count = 0
    updated_count = 0

    for key, entry in all_data.items():
        if key not in series_meta:
            continue

        prev_entry = latest_obs.get(key)
        new_val = entry["value"]
        new_date = entry["date"]

        # One row per calendar/release date per series: a new date gets a new
        # row; a same-day value change (e.g. an intraday VIX quote) updates
        # that day's row in place rather than spamming a new one every run.
        if prev_entry is None or prev_entry["date"] != new_date:
            insert_observation(key, new_date, new_val)
            new_count += 1
            logger.info(
                f"Recorded new observation for {series_meta[key]['label']}: "
                f"{new_val}{series_meta[key]['unit']} (date: {new_date})"
            )
        elif abs(new_val - prev_entry["value"]) >= 0.0001:
            update_observation(prev_entry["id"], new_val)
            updated_count += 1
            logger.info(
                f"Updated today's observation for {series_meta[key]['label']}: "
                f"{new_val}{series_meta[key]['unit']} (date: {new_date})"
            )

    logger.info(
        f"Check complete: {new_count} new observation(s) recorded, "
        f"{updated_count} same-day observation(s) refreshed."
    )
