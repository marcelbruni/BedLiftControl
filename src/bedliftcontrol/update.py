"""Looks on GitHub for a newer version and installs it with git.

The Pi has no keyboard, so the update procedure from DEPLOYMENT.md is wrapped here and
offered as a button. Only the two git steps are run: the app is an editable install, so
a pull is enough for code changes. If a release ever changes the dependencies, that one
still needs the terminal.

`data/config.json` is checked in and the running app keeps writing to it, so a pull would
be refused. The file is therefore discarded before pulling - the caller writes the live
values back afterwards, which is what keeps the bed position across an update.
"""

import logging
import os
import subprocess
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_DIR = str(Path(__file__).resolve().parents[2])
CHECK_INTERVAL_SECONDS = 1800
# short, so the button turns up soon after the phone hotspot comes back
RETRY_INTERVAL_SECONDS = 300
FETCH_TIMEOUT = 30
PULL_TIMEOUT = 120
CONFIG_PATH = "data/config.json"


def _git(*args, timeout: int = FETCH_TIMEOUT) -> subprocess.CompletedProcess:
    """git in the project directory, never prompting - there is nobody to answer."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    return subprocess.run(
        ["git", "-C", REPO_DIR, *args],
        capture_output=True, text=True, timeout=timeout, env=env, check=False,
    )


class UpdateChecker:
    """Counts the commits the checkout is behind its remote branch."""

    def __init__(self, interval: int = CHECK_INTERVAL_SECONDS,
                 retry_interval: int = RETRY_INTERVAL_SECONDS):
        self.interval = interval
        self.retry_interval = retry_interval
        self.pending = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    @property
    def update_available(self) -> bool:
        return self.pending > 0

    def check_once(self) -> bool:
        """True when the remote could be reached, whatever it answered."""
        try:
            fetched = _git("fetch", "--quiet")
            if fetched.returncode != 0:
                logger.info("Update check failed: %s", fetched.stderr.strip())
                return False
            counted = _git("rev-list", "--count", "HEAD..@{u}")
            if counted.returncode != 0:
                logger.warning("Cannot compare with the remote branch: %s",
                               counted.stderr.strip())
                return False
        except (OSError, subprocess.SubprocessError) as error:
            logger.info("Update check failed (%s)", error)
            return False
        with self._lock:
            self.pending = int(counted.stdout.strip() or 0)
        if self.pending:
            logger.info("Update available: %s commits behind", self.pending)
        return True

    def apply(self) -> bool:
        """Discard the local config, fast-forward. True when the checkout moved."""
        steps = (
            (("checkout", "--", CONFIG_PATH), FETCH_TIMEOUT),
            (("pull", "--ff-only"), PULL_TIMEOUT),
        )
        for args, timeout in steps:
            try:
                result = _git(*args, timeout=timeout)
            except (OSError, subprocess.SubprocessError) as error:
                logger.error("Update step %s failed (%s)", args[0], error)
                return False
            if result.returncode != 0:
                logger.error("Update step %s failed: %s", args[0], result.stderr.strip())
                return False
        with self._lock:
            self.pending = 0
        logger.info("Updated to the latest version")
        return True

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            reached = self.check_once()
            self._stop.wait(self.interval if reached else self.retry_interval)
