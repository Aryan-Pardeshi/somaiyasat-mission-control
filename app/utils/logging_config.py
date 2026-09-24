"""Application logging setup."""

import logging
from logging.handlers import RotatingFileHandler
from app import config


def setup_logging() -> None:
    """Write normal activity to a rotating file and warnings to console."""
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return
    root.setLevel(logging.INFO)
    file_handler = RotatingFileHandler(config.LOG_FILE, maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    for handler in (file_handler, console):
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
