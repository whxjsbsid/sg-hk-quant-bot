import logging
from pathlib import Path


def setup_activity_logger(log_path: str = "logs/bot.log") -> logging.Logger:
    log_file = Path(log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("bot")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    resolved_log_file = log_file.resolve()

    has_same_file_handler = any(
        isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename).resolve() == resolved_log_file
        for handler in logger.handlers
    )

    if not has_same_file_handler:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
