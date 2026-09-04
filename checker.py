from loguru import logger
from macro.fred import fetch_fred_data
from macro.live import fetch_live_data
from macro.treasury import fetch_treasury_data
from db import (
    get_series_metadata,
    get_latest_observations,
    upsert_observation,
    record_run,
)


def run_check() -> None:
    series_meta = get_series_metadata()
    latest_obs = get_latest_observations()

    sources = {
        "fred": fetch_fred_data(),
        "live": fetch_live_data(),
        "treasury": fetch_treasury_data(),
    }
    failed_sources = [name for name, data in sources.items() if not data]
    for name in failed_sources:
        logger.warning(f"Source '{name}' returned no data this run.")

    all_data: dict = {}
    for data in sources.values():
        all_data.update(data)

    # Derived series are dated with their most recent input date. Dating them
    # by a specific input instead would pin them to that input's release
    # cadence — e.g. WALCL is weekly, so using its date would collapse a
    # whole week of daily RRP/TGA movement into a single row.
    if "sofr" in all_data and "effr" in all_data:
        all_data["sofr_effr_spread"] = {
            "value": round(all_data["sofr"]["value"] - all_data["effr"]["value"], 4),
            "date": max(all_data["sofr"]["date"], all_data["effr"]["date"]),
        }

    if "walcl" in all_data and "rrp" in all_data and "tga" in all_data:
        all_data["fed_net_liquidity"] = {
            "value": round(
                all_data["walcl"]["value"] - all_data["rrp"]["value"] - all_data["tga"]["value"], 3
            ),
            "date": max(
                all_data["walcl"]["date"], all_data["rrp"]["date"], all_data["tga"]["date"]
            ),
        }

    new_count = 0
    updated_count = 0
    stale_count = 0

    for key, entry in all_data.items():
        if key not in series_meta:
            logger.warning(f"Fetched '{key}' but it has no series_metadata entry - skipping.")
            continue

        label = series_meta[key]["label"]
        unit = series_meta[key]["unit"]
        prev_entry = latest_obs.get(key)
        new_val = entry["value"]
        new_date = entry["date"]

        # A feed briefly reporting an older date than what we already hold
        # must not be stored, or it would look like the newest value.
        if prev_entry is not None and new_date < prev_entry["date"]:
            logger.warning(
                f"Ignoring stale {label}: feed reports {new_date}, "
                f"but {prev_entry['date']} is already stored."
            )
            stale_count += 1
            continue

        # One row per calendar/release date per series: a new date gets a new
        # row; a same-day value change (e.g. an intraday VIX quote) updates
        # that day's row in place rather than spamming a new one every run.
        if prev_entry is None or prev_entry["date"] != new_date:
            upsert_observation(key, new_date, new_val)
            new_count += 1
            logger.debug(
                f"Recorded new observation for {label}: {new_val}{unit} (date: {new_date})"
            )
        elif abs(new_val - prev_entry["value"]) >= 0.0001:
            upsert_observation(key, new_date, new_val)
            updated_count += 1
            logger.debug(
                f"Updated same-day observation for {label}: {new_val}{unit} (date: {new_date})"
            )

    if len(failed_sources) == len(sources):
        status = "failed"
    elif failed_sources:
        status = "partial"
    else:
        status = "ok"
    record_run(status)

    logger.info(
        f"Check complete [{status}]: {new_count} new observation(s) recorded, "
        f"{updated_count} same-day observation(s) refreshed, "
        f"{stale_count} stale reading(s) ignored."
    )
