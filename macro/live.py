import yfinance as yf
from loguru import logger

LIVE_TICKERS = {
    "vix":    "^VIX",
    "skew":   "^SKEW",
    "move":   "^MOVE",
}


def fetch_live_data() -> dict:
    result = {}
    for key, symbol in LIVE_TICKERS.items():
        try:
            hist = yf.Ticker(symbol).history(period="5d")
            if hist.empty:
                logger.warning(f"Yahoo Finance returned no history for '{key}' ({symbol}).")
                continue
            last = hist.iloc[-1]
            result[key] = {
                "value": round(float(last["Close"]), 2),
                "date": last.name.date().isoformat(),
            }
        except Exception as exc:
            logger.warning(f"Yahoo Finance fetch failed for '{key}' ({symbol}): {exc}")
    return result
