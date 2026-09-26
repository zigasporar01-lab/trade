from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            # colors=False: ANSI color codes survive being piped/redirected to a
            # file (e.g. `python main.py | Tee-Object -FilePath log.txt` on
            # Windows), splitting fields like `onchain_verdict=SAFE` into
            # non-contiguous bytes and silently breaking substring searches
            # over the saved log.
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
