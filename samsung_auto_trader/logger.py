"""
logger.py – Dual-output logging for Samsung Auto Trader.

Provides a single factory function that returns a logger writing to:
  • Console  – INFO level (human-friendly, concise)
  • File     – DEBUG level (full detail for post-mortem analysis)

Log files are stored under samsung_auto_trader/logs/ with daily rotation
(one file per calendar day, named trading_YYYYMMDD.log).
"""

import logging
import os
from datetime import datetime
import config
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# Directory where log files are stored
_LOG_DIR: Path = Path(__file__).resolve().parent / "logs"

# Shared format string
_LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"


def setup_logger(name: str = "samsung_trader") -> logging.Logger:
    """Create and configure a logger with console + daily-rotating file handlers.

    Calling this function multiple times with the same *name* is safe;
    handlers are only attached once.

    Args:
        name: Logger name (appears in every log line).

    Returns:
        A fully-configured ``logging.Logger`` instance.
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers on repeated calls
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)  # Capture everything; handlers filter

    formatter = logging.Formatter(_LOG_FORMAT)
    # 🌟 Ensure log timestamps are ALWAYS in KST, regardless of system timezone
    formatter.converter = lambda *args: config.get_now().timetuple()

    # --- Console handler (INFO and above) ---
    class UIFormatter(logging.Formatter):
        def format(self, record):
            msg = record.getMessage()
            if record.levelno == logging.ERROR:
                return f"❌ [오류] {msg}"
            elif record.levelno == logging.WARNING:
                return f"⚠️ [경고] {msg}"
            else:
                return msg

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(UIFormatter())
    logger.addHandler(console_handler)

    # --- File handler (DEBUG and above, daily rotation) ---
    os.makedirs(_LOG_DIR, exist_ok=True)

    # Initial filename uses today's date in KST
    log_filename = _LOG_DIR / f"trading_{config.get_now():%Y%m%d}.log"

    file_handler = TimedRotatingFileHandler(
        filename=str(log_filename),
        when="midnight",
        interval=1,
        backupCount=30,      # Keep up to 30 days of logs
        encoding="utf-8",
    )
    file_handler.suffix = "%Y%m%d"  # Rotated file suffix
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.debug("Logger '%s' initialised (console=INFO, file=DEBUG)", name)
    return logger
