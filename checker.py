from loguru import logger
from macro.fred import fetch_fred_data
from macro.live import fetch_live_data
from macro.treasury import fetch_treasury_data
from db import (
    get_series_metadata,
    get_latest_observations,
    get_last_notified_baselines,
    insert_observation,
    upsert_pending_update,
    get_pending_update,
)


def run_check() -> None:
    logger.info("Checking macro data for new observations...")
    series_meta = get_series_metadata()
    latest_obs = get_latest_observations()
    baselines = get_last_notified_baselines()

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

    new_observations_count = 0
    staged_diffs = {}

    for key, entry in all_data.items():
        if key not in series_meta:
            continue

        prev_entry = latest_obs.get(key)
        new_val = entry["value"]
        new_date = entry["date"]

        # 1. Insert new observation if value changed or never observed before
        if prev_entry is None or abs(new_val - prev_entry["value"]) >= 0.0001:
            insert_observation(key, new_date, new_val)
            new_observations_count += 1
            logger.info(
                f"Recorded new observation for {series_meta[key]['label']}: "
                f"{new_val}{series_meta[key]['unit']} (date: {new_date})"
            )

        # 2. Check significance against last notified baseline
        baseline = baselines.get(key)
        threshold = series_meta[key].get("threshold", 0.0)

        if baseline is None:
            # First time this series is observed: establishes baseline, stage initial notification
            staged_diffs[key] = {
                "old": new_val,
                "new": new_val,
                "date": new_date,
                "delta": 0.0,
            }
        else:
            delta = round(new_val - baseline["value"], 4)
            is_significant = (threshold == 0.0 and abs(delta) >= 0.0001) or (
                threshold > 0.0 and abs(delta) >= threshold
            )
            if is_significant:
                staged_diffs[key] = {
                    "old": baseline["value"],
                    "new": new_val,
                    "date": new_date,
                    "delta": delta,
                }

    # 3. Update pending updates queue if we have staged diffs or need to consolidate with existing pending
    existing_pending = get_pending_update()
    if staged_diffs or existing_pending:
        upsert_pending_update(staged_diffs, series_meta)

    logger.info(
        f"Check complete: {new_observations_count} new observation(s) recorded, "
        f"{len(staged_diffs)} staged significant movement(s)."
    )
