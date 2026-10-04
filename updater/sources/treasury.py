import requests
from loguru import logger

# The Fiscal Data API moved from /services/api/v1/ to /services/api/fiscal_service/v1/.
# The old path now returns a 404 HTML page for every request.
TREASURY_API = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1"
    "/accounting/dts/operating_cash_balance"
)
HTTP_TIMEOUT = 15

# The endpoint returns FOUR rows per date (opening balance, deposits,
# withdrawals, closing balance), so the account type must be filtered
# explicitly or the wrong figure gets picked up.
TGA_CLOSING = "Treasury General Account (TGA) Closing Balance"

# Quirk: `close_today_bal` is always the string "null" in this dataset. The
# actual figure for the closing-balance ROW is carried in `open_today_bal`.
VALUE_FIELD = "open_today_bal"


def fetch_treasury_data() -> dict:
    params = {
        "filter": f"account_type:eq:{TGA_CLOSING}",
        "sort": "-record_date",
        "page[size]": 1,
        "fields": f"record_date,{VALUE_FIELD}",
    }
    try:
        resp = requests.get(TREASURY_API, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            logger.warning("Treasury API returned no TGA closing-balance rows.")
            return {}
        row = data[0]
        raw = row.get(VALUE_FIELD)
        if raw in (None, "", "null"):
            logger.warning(f"Treasury TGA row for {row.get('record_date')} has no usable balance.")
            return {}
        value = round(float(raw) / 1000, 3)  # -> billions
        return {"tga": {"value": value, "date": row["record_date"]}}
    except Exception as exc:
        logger.warning(f"Treasury API fetch failed: {exc}")
        return {}