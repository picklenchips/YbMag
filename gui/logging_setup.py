"""Logging configuration for YbMag.

Call setup_logging() once at application startup (in app.py) before any other
code runs. After that, every module gets its own logger via:

    import logging
    logger = logging.getLogger(__name__)
"""

import logging
import logging.handlers
import sys
from pathlib import Path


def setup_logging() -> None:
    """
    Set up logging for the YbMag application.
    
    * Logs are written to a rotating file handler that limits the file size to 5 MB and keeps 3 backup files.
    * Unhandled exceptions are logged to the file as well.
    * Noisy third-party loggers are suppressed at the WARNING level.
    """
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        log_dir / "ybmag.log",
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    # Route unhandled exceptions to the log file.
    _orig_excepthook = sys.excepthook

    def _excepthook(exc_type, exc_value, exc_tb):
        logging.getLogger("ybmag").critical(
            "Unhandled exception", exc_info=(exc_type, exc_value, exc_tb)
        )
        _orig_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    # Suppress noisy third-party loggers at WARNING level.
    for name in ("PIL", "matplotlib", "torch", "qutip"):
        logging.getLogger(name).setLevel(logging.WARNING)
