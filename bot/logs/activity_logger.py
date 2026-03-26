# bot/logs/activity_logger.py

import logging
from pathlib import Path


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
DEFAULT_LOG_LEVEL = logging.INFO


def setup_activity_logger(
    log_path: str = "bot/logs/bot.log",
    logger_name: str = "bot",
) -> logging.Logger:
    log_file = Path(log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    resolved_log_file = log_file.resolve()

    logger = logging.getLogger(logger_name)
    logger.setLevel(DEFAULT_LOG_LEVEL)
    logger.propagate = False

    formatter = logging.Formatter(LOG_FORMAT)

    for handler in logger.handlers:
        if not isinstance(handler, logging.FileHandler):
            continue

        try:
            handler_path = Path(handler.baseFilename).resolve()
        except Exception:
            continue

        if handler_path == resolved_log_file:
            handler.setLevel(DEFAULT_LOG_LEVEL)
            handler.setFormatter(formatter)
            return logger

    file_handler = logging.FileHandler(resolved_log_file, encoding="utf-8")
    file_handler.setLevel(DEFAULT_LOG_LEVEL)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
