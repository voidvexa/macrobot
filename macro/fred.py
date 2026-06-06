import requests
from config import settings

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
HTTP_TIMEOUT = 15

SERIES = {
    "us10y":     "DGS10",
    "hy_spread": "BAMLH0A0HYM2",
    "ig_spread": "BAMLC0A0CM",
    "sofr":      "SOFR",
    "effr":      "DFF",
    "repo":      "RPONTSYD",
    "rrp":       "RRPONTSYD",
}

BPS_SERIES = {"hy_spread", "ig_spread"}


def fetch_fred_data() -> dict:
    if not settings.fred_api_key:
        return {}

    result = {}
    for key, series_id in SERIES.items():
        obs = _fetch_series(series_id)
        if not obs:
            continue
        entry: dict = {"value": obs[0]["value"], "date": obs[0]["date"]}
        if key in BPS_SERIES:
            entry["value"] = round(entry["value"] * 100, 1)
        result[key] = entry
    return result


def _fetch_series(series_id: str, limit: int = 1) -> list[dict]:
    params = {
        "series_id": series_id,
        "api_key": settings.fred_api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    try:
        resp = requests.get(FRED_BASE, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        return []

    out = []
    for o in resp.json().get("observations", []):
        raw = o.get("value")
        if raw in (None, ".", ""):
            continue
        try:
            out.append({"value": float(raw), "date": o["date"]})
        except (TypeError, ValueError):
            continue
    return out
