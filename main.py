import logging
import sys
from pathlib import Path

from loguru import logger

from checker import run_check
from config import settings
from db import init_db, record_run

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger.remove()
logger.add(
    sys.stderr,
    level=settings.log_level,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    colorize=sys.stderr.isatty(),
)
# Daily rotate + 7-day gzip retention so a 2-hourly cron cannot grow an
# unbounded log. Per-observation detail is DEBUG; INFO is one summary line.
logger.add(
    LOG_DIR / "macrobot.log",
    level=settings.log_level,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
    rotation="00:00",
    retention="7 days",
    compression="gz",
    colorize=False,
)

# yfinance (and peewee, if it ever logs) use stdlib logging, which loguru
# does not capture. Keep them quiet so they cannot fill the cron capture.
logging.getLogger("yfinance").setLevel(logging.ERROR)
logging.getLogger("peewee").setLevel(logging.ERROR)

if __name__ == "__main__":
    try:
        init_db()
        run_check()
    except Exception:
        # Exit non-zero so systemd marks the unit failed instead of the run
        # disappearing silently into the journal.
        logger.exception("Macrobot run failed")
        try:
            record_run("failed")
        except Exception:
            logger.error("Could not record the failed-run marker.")
        sys.exit(1)
