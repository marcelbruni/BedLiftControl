"""Where the log goes.

The Pi starts the app from a desktop autostart entry with `Terminal=false`, so anything
printed to stderr is gone. Without a file on disk, a failure on the road leaves nothing
to look at - which is why the update button could only ever say "Fehlgeschlagen".

Crashes are routed here as well: an unhandled exception reaches stderr through the
interpreter, not through logging, so the three hooks below put it in the file too.
"""

import logging
import logging.handlers
import sys
import threading
from collections import deque
from pathlib import Path

logger = logging.getLogger(__name__)

LOG_FILE = str(Path(__file__).resolve().parents[2] / "data" / "bedliftcontrol.log")
# 1 MB a file, four files: enough history for a trip, small enough for an SD card
MAX_BYTES = 1_000_000
BACKUP_COUNT = 3
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
# what the panel shows: a few hours of a quiet machine, and enough of a noisy
# one to see what led up to the last entry
TAIL_LINES = 400


def configure(path: str = LOG_FILE, level: int = logging.INFO) -> None:
    """File and console together: the file for the Pi, the console for development."""
    handlers: list = [logging.StreamHandler()]
    try:
        handlers.append(logging.handlers.RotatingFileHandler(
            path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"))
    except OSError as error:
        # a read-only or full disk must not stop the bed from working
        print(f"Could not open the log file {path} ({error})", file=sys.stderr)
    logging.basicConfig(level=level, format=LOG_FORMAT, handlers=handlers, force=True)
    _catch_crashes()


def _catch_crashes() -> None:
    sys.excepthook = _log_exception
    threading.excepthook = _log_thread_exception


def _log_exception(kind, value, traceback) -> None:
    logger.critical("Unhandled exception", exc_info=(kind, value, traceback))


def _log_thread_exception(args) -> None:
    if args.exc_type is SystemExit:
        return
    logger.critical("Unhandled exception in thread %s", args.thread.name if args.thread else "?",
                    exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def read_tail(path: str = LOG_FILE, lines: int = TAIL_LINES) -> str:
    """The last `lines` of the log, for showing it on the panel.

    Whole lines and in order: a traceback is several of them and is unreadable
    rearranged or cut in the middle.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            kept = deque(handle, maxlen=lines)
    except OSError as error:
        logger.info("Could not read the log %s (%s)", path, error)
        return ""
    return "".join(kept).rstrip()


def log_callback_exception(kind, value, traceback) -> None:
    """For Tk's own callbacks - every timer and button press runs inside one, and Tk
    prints their exceptions straight to stderr unless this is hung on the root window.

    Three arguments, not four: Tk looks the attribute up on the instance, so nothing
    is bound and no widget is passed.
    """
    logger.critical("Unhandled exception in a Tk callback", exc_info=(kind, value, traceback))
