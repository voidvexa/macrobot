import requests
from config import settings

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
HTTP_TIMEOUT = 15

SERIES = {
    "fed_funds_rate": "DFF",
    "fed_funds_target_upper": "DFEDTARU",
    "fed_funds_target_lower": "DFEDTARL",
    "ten_year_yield": "DGS10",
    "two_year_yield": "DGS2",
    "cpi": "CPIAUCSL",
    "core_cpi": "CPILFESL",
    "unemployment_rate": "UNRATE",
    "hy_spread": "BAMLH0A0HYM2",
    "yield_spread": "T10Y2Y",
}

# Series that need 13 observations to compute YoY
YOY_SERIES = {"cpi", "core_cpi"}


def fetch_fred_data() -> dict:
    """Returns {key: {"value": float, "date": str, "yoy"?: float}}. Missing on fetch failure."""
    if not settings.fred_api_key:
        return {}

    result = {}
    for key, series_id in SERIES.items():
        limit = 14 if key in YOY_SERIES else 1
        obs = _fetch_series(series_id, limit=limit)
        if not obs:
            continue

        entry: dict = {"value": obs[0]["value"], "date": obs[0]["date"]}

        if key == "hy_spread":
            entry["value"] = round(entry["value"] * 100, 1)

        if key in YOY_SERIES and len(obs) >= 13:
            year_ago = obs[12]["value"]
            if year_ago:
                entry["yoy"] = round((obs[0]["value"] - year_ago) / year_ago * 100, 2)

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
