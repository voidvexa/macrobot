import sys
from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from checker import run_check

logger.remove()
logger.add(
    sys.stderr,
    level=settings.log_level,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    colorize=True,
)

if __name__ == "__main__":
    logger.info("Macrobot starting — polling macro data every hour")
    run_check()

    scheduler = BlockingScheduler(timezone=settings.timezone)
    scheduler.add_job(run_check, IntervalTrigger(hours=1))
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Shutting down")
