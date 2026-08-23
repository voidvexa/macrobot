import sys
from loguru import logger
from config import settings
from db import init_db
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
    init_db()
    run_check()
    logger.info("Macrobot check execution finished successfully")

