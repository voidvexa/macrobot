import requests
from loguru import logger
from config import settings

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
HTTP_TIMEOUT = 15

SERIES = {
    "us10y":     "DGS10",
    "hy_spread": "BAMLH0A0HYM2",
    "ccc_spread":"BAMLH0A3HYC",
    "ig_spread": "BAMLC0A0CM",
    "sofr":      "SOFR",
    "effr":      "DFF",
    "rrp":       "RRPONTSYD",
    "walcl":     "WALCL",
    "cpi":       "CPIAUCSL",
    "core_cpi":  "CPILFESL",
    "drtscilm":  "DRTSCILM",
    "usblr":     "DPRIME",
    "payems":    "PAYEMS",
    "icsa":      "ICSA",
    "unrate":    "UNRATE",
    "indpro":    "INDPRO",
    "rsafs":     "RSAFS",
    "core_pce":  "PCEPILFE",
    "tga_weekly":"WDTGAL",
    "m2sl":      "M2SL",
    "totbkcr":   "TOTBKCR",
    "dtwexbgs":  "DTWEXBGS",
    "t10y2y":    "T10Y2Y",
    "cfnai":     "CFNAI",
    "permit":    "PERMIT",
    "real_pce":  "PCEC96",
    "real_gdp":  "GDPC1",
    "ccsa":      "CCSA",
    "pce":       "PCEPI",
    "ppi":       "PPIFIS",
    "ahe":       "CES0500000003",
    "t5yie":     "T5YIE",
    "t5yifr":    "T5YIFR",
    "wresbal":   "WRESBAL",
    "nfci":      "NFCI",
    "stlfsi4":   "STLFSI4",
    "t10y3m":    "T10Y3M",
}

BPS_SERIES = {"hy_spread", "ig_spread", "ccc_spread"}
# tga isn't fetched here — it comes from macro/treasury.py, which is more
# authoritative (filters to the TGA closing-balance row specifically) and is
# what fed_net_liquidity uses. tga_weekly (WDTGAL) is FRED's weekly Wednesday
# level, stored as its own series alongside it.
# wresbal is the H.4.1 reserve-balance week average, same millions-of-dollars
# unit as walcl.
MILLIONS_TO_BILLIONS_SERIES = {"walcl", "tga_weekly", "rsafs", "wresbal"}

# Series we report as year-over-year percent change rather than the raw index
# or dollar level. FRED computes the YoY rate server-side via units=pc1, so
# we receive e.g. 3.4 (percent) instead of a level that is hard to read as
# an inflation rate. These series are monthly, so they move at most once per
# release. pce (PCEPI) and ppi (PPIFIS) are price indexes, same treatment as
# CPI. ahe (CES0500000003) is average hourly earnings, stored as wage growth
# rather than dollars per hour.
YOY_SERIES = {"cpi", "core_cpi", "core_pce", "indpro", "pce", "ppi", "ahe"}


def fetch_fred_data() -> dict:
    if not settings.fred_api_key:
        logger.warning("FRED_API_KEY is not set - skipping every FRED series.")
        return {}

    result = {}
    for key, series_id in SERIES.items():
        units = "pc1" if key in YOY_SERIES else "lin"
        obs = _fetch_series(series_id, units=units)
        if not obs:
            logger.warning(f"No usable FRED observation for '{key}' ({series_id}).")
            continue
        entry: dict = {"value": obs[0]["value"], "date": obs[0]["date"]}
        if key in BPS_SERIES:
            entry["value"] = round(entry["value"] * 100, 1)
        elif key in YOY_SERIES:
            entry["value"] = round(entry["value"], 1)
        elif key in MILLIONS_TO_BILLIONS_SERIES:
            entry["value"] = round(entry["value"] / 1000, 3)
        result[key] = entry
    return result


def _fetch_series(series_id: str, limit: int = 1, units: str = "lin") -> list[dict]:
    params = {
        "series_id": series_id,
        "api_key": settings.fred_api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
        "units": units,
    }
    try:
        resp = requests.get(FRED_BASE, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        # Never log the exception verbatim: its message embeds the request URL,
        # which carries the FRED api_key as a query parameter.
        status = getattr(getattr(exc, "response", None), "status_code", None)
        detail = f"HTTP {status}" if status else type(exc).__name__
        logger.warning(f"FRED request failed for {series_id}: {detail}")
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
