import sys
from loguru import logger
from config import settings
from db import init_db, record_run
from checker import run_check

logger.remove()
logger.add(
    sys.stderr,
    level=settings.log_level,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    colorize=True,
)

if __name__ == "__main__":
    logger.info("Macrobot starting - single check execution")
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
    logger.info("Macrobot check execution finished successfully")
