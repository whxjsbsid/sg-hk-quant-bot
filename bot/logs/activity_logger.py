import logging
from pathlib import Path


def setup_activity_logger(
    log_path: str = "bot/logs/bot.log",
    logger_name: str = "bot",
) -> logging.Logger:
    log_file = Path(log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    resolved_log_file = log_file.resolve()

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    has_same_file_handler = False

    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler):
            try:
                handler_path = Path(handler.baseFilename).resolve()
                if handler_path == resolved_log_file:
                    has_same_file_handler = True
                    handler.setFormatter(formatter)
            except Exception:
                pass

    if not has_same_file_handler:
        file_handler = logging.FileHandler(resolved_log_file, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
