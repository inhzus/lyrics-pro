"""Bounded, local diagnostic events. Never send logs over the bridge stdout."""
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

SUPPORT = Path.home() / "Library/Application Support/Lyrics Pro"
logger = logging.getLogger("lyrics_pro")
logger.addHandler(logging.NullHandler())


def event(name, **fields):
    # Call sites supply metadata only, never lyrics, artwork, or HTTP bodies.
    record = {"event": name, **{k: str(v)[:512] for k, v in fields.items()}}
    logger.info(json.dumps(record, ensure_ascii=False))


def setup(*, bridge=False, directory=None):
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        if bridge:
            handler = logging.StreamHandler(sys.stderr)
        else:
            folder = Path(directory) if directory else SUPPORT / "Logs"
            folder.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(folder / "cli.log", maxBytes=2 * 1024 * 1024,
                                          backupCount=4, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
    except OSError:
        logger.addHandler(logging.NullHandler())
    logging.raiseExceptions = False

