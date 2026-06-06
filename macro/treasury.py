import requests

TREASURY_API = "https://api.fiscaldata.treasury.gov/services/api/v1/accounting/dts/operating_cash_balance"
HTTP_TIMEOUT = 15


def fetch_treasury_data() -> dict:
    params = {
        "sort": "-record_date",
        "page[size]": 1,
        "fields": "record_date,open_today_bal",
    }
    try:
        resp = requests.get(TREASURY_API, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            return {}
        row = data[0]
        value = round(float(row["open_today_bal"]) / 1000, 1)  # millions → billions
        return {"tga": {"value": value, "date": row["record_date"]}}
    except Exception:
        return {}
