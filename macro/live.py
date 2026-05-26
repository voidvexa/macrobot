import yfinance as yf

LIVE_TICKERS = {
    "vix": "^VIX",
    "skew": "^SKEW",
}


def fetch_live_data() -> dict:
    """Returns {key: {"value": float, "date": str}}. Missing on fetch failure."""
    result = {}
    for key, symbol in LIVE_TICKERS.items():
        try:
            hist = yf.Ticker(symbol).history(period="5d")
            if hist.empty:
                continue
            last = hist.iloc[-1]
            result[key] = {
                "value": round(float(last["Close"]), 2),
                "date": last.name.date().isoformat(),
            }
        except Exception:
            pass
    return result
