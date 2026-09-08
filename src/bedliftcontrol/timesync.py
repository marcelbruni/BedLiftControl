"""Keeps the shown clock right when the machine's own clock is not.

A Raspberry Pi has no battery backed real time clock. Without a network it starts up
with whatever time it last saw and then drifts. NTP fixes that when the Pi is online,
but a camper is offline most of the time and the Pi may have booted long before it ever
saw a network.

So the offset between the machine clock and an internet reference is measured once and
kept. The shown time is simply "machine clock + offset": it keeps ticking at full
accuracy while offline and gets re-anchored whenever the network comes back.

The reference is the HTTP Date header of the weather API the app already talks to. No
extra service, no API key, no additional host to reach - and it works where the public
time APIs do not (worldtimeapi.org and cloudflare.com are both unreachable from the
network this was developed on).

Accuracy: the Date header has one second resolution, so the true server time lies
somewhere inside that second - half a second is added back to centre the estimate. The
round trip is measured and its midpoint used as the local reference, which removes most
of the network latency. What remains is comfortably under a second, which the display
(hours, minutes, seconds) cannot resolve anyway.
"""

import logging
import subprocess
import sys
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from bedliftcontrol import clock

logger = logging.getLogger(__name__)

TIME_URL = "https://api.open-meteo.com/v1/forecast?latitude=0&longitude=0"
SYNC_INTERVAL_SECONDS = 3600  # hourly, as the machine clock drifts slowly
HTTP_TIMEOUT = 8
# The Date header is truncated to the second, so the real instant is uniformly spread
# over the following second. Adding half of it centres the estimate.
HEADER_RESOLUTION = timedelta(seconds=0.5)
# Below this the machine clock is fine and rewriting it would be pointless churn.
SYSTEM_CLOCK_THRESHOLD = timedelta(seconds=2)


def format_offset(offset: timedelta) -> str:
    """Readable seconds. timedelta renders a small negative value as '-1 day, 23:59:59.89',
    which in a log line reads like a catastrophe rather than 110ms behind."""
    return f"{offset.total_seconds():+.3f}s"


def fetch_internet_utc(url: str = TIME_URL, timeout: int = HTTP_TIMEOUT) -> tuple[datetime, datetime]:
    """Return (server UTC, the local UTC instant it corresponds to).

    Raises on any network trouble; callers treat that as "stay offline".
    """
    request = urllib.request.Request(url, method="HEAD")
    before = datetime.now(timezone.utc)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        header = response.headers["Date"]
    after = datetime.now(timezone.utc)
    if not header:
        raise ValueError("response carried no Date header")
    server = parsedate_to_datetime(header) + HEADER_RESOLUTION
    local_midpoint = before + (after - before) / 2
    return server, local_midpoint


def set_system_clock(offset: timedelta) -> bool:
    """Push the correction into the operating system clock. Linux only.

    Runs `sudo -n`, so it never prompts: without the sudoers entry it simply fails and
    is logged. The in-app clock is correct either way, this only helps everything else
    on the Pi (file timestamps, logs, cron).
    """
    if not sys.platform.startswith("linux"):
        logger.debug("Not setting the system clock on %s", sys.platform)
        return False
    corrected = datetime.now(timezone.utc) + offset
    stamp = corrected.strftime("%Y-%m-%d %H:%M:%S")
    try:
        result = subprocess.run(
            ["sudo", "-n", "date", "-u", "-s", stamp],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("Could not run date to set the system clock (%s)", error)
        return False
    if result.returncode != 0:
        logger.warning("Setting the system clock failed: %s", result.stderr.strip() or result.returncode)
        return False
    logger.info("System clock set to %s UTC (was off by %s)", stamp, format_offset(offset))
    return True


class TimeSync:
    """Machine clock plus a measured offset, re-anchored hourly while online."""

    def __init__(
        self,
        url: str = TIME_URL,
        interval: int = SYNC_INTERVAL_SECONDS,
        adjust_system_clock: bool = True,
    ):
        self.url = url
        self.interval = interval
        self.adjust_system_clock = adjust_system_clock
        self.offset = timedelta(0)
        self.last_sync: datetime | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def synced(self) -> bool:
        """False means the shown time is the bare machine clock."""
        return self.last_sync is not None

    def now(self) -> datetime:
        """Local wall clock time, corrected by whatever offset was last measured."""
        with self._lock:
            offset = self.offset
        return clock.now() + offset

    def refresh_once(self) -> bool:
        try:
            server, local_midpoint = fetch_internet_utc(self.url)
        except Exception:  # network boundary: being offline is normal, never crash
            logger.warning("Time sync failed, keeping the previous offset", exc_info=True)
            return False
        offset = server - local_midpoint
        with self._lock:
            self.offset = offset
            self.last_sync = clock.now()
        logger.info("Time synced, machine clock is off by %s", format_offset(offset))
        if self.adjust_system_clock and abs(offset) >= SYSTEM_CLOCK_THRESHOLD:
            if set_system_clock(offset):
                # the machine clock now carries the correction itself - keeping the
                # offset on top of it would apply the very same correction twice
                with self._lock:
                    self.offset = timedelta(0)
        return True

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.refresh_once()
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
