"""Installs a newer version from GitHub, on request.

The Pi has no keyboard, so the git steps from DEPLOYMENT.md are wrapped here and offered
as a button in the settings. Looking and installing are one action: nothing runs in the
background, nothing is polled - the check happens when the button is pressed.

Only code changes are covered: the app is an editable install, so a pull is enough. If a
release ever changes the dependencies, that one still needs the terminal.

`data/config.json` is checked in and the running app keeps writing to it, so a pull would
be refused. The file is therefore discarded before pulling - the caller writes the live
values back afterwards, which is what keeps the bed position across an update.
"""

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_DIR = str(Path(__file__).resolve().parents[2])
FETCH_TIMEOUT = 30
PULL_TIMEOUT = 120
CONFIG_PATH = "data/config.json"
UNKNOWN_VERSION = "unbekannt"
VERSION_FORMAT = "%h · %ad"
VERSION_DATE_FORMAT = "format:%d.%m.%Y %H:%M"

UPDATED = "updated"
UP_TO_DATE = "up_to_date"
FAILED = "failed"


def _git(*args, timeout: int = FETCH_TIMEOUT) -> subprocess.CompletedProcess:
    """git in the project directory, never prompting - there is nobody to answer."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    return subprocess.run(
        ["git", "-C", REPO_DIR, *args],
        capture_output=True, text=True, timeout=timeout, env=env, check=False,
        # git speaks UTF-8; without this the locale codepage mangles anything non-ASCII
        encoding="utf-8", errors="replace",
    )


class Updater:
    """Looks for a newer version on GitHub and installs it in the same go."""

    def install(self) -> str:
        """One of UPDATED, UP_TO_DATE or FAILED."""
        pending = self._pending()
        if pending is None:
            return FAILED
        if not pending:
            logger.info("Already on the latest version")
            return UP_TO_DATE
        logger.info("Installing %s new commit(s)", pending)
        return UPDATED if self._pull() else FAILED

    def version(self) -> str:
        """The checked-out commit and its date - enough to tell two states apart."""
        result = self._run(("log", "-1", f"--format={VERSION_FORMAT}",
                            f"--date={VERSION_DATE_FORMAT}"))
        if result is None or result.returncode != 0:
            return UNKNOWN_VERSION
        return result.stdout.strip() or UNKNOWN_VERSION

    def _pending(self):
        """Commits the checkout is behind its remote branch, or None when git failed."""
        fetched = self._run(("fetch", "--quiet"))
        if fetched is None or fetched.returncode != 0:
            if fetched is not None:
                logger.info("Update check failed: %s", fetched.stderr.strip())
            return None
        counted = self._run(("rev-list", "--count", "HEAD..@{u}"))
        if counted is None or counted.returncode != 0:
            if counted is not None:
                logger.warning("Cannot compare with the remote branch: %s",
                               counted.stderr.strip())
            return None
        return int(counted.stdout.strip() or 0)

    def _pull(self) -> bool:
        steps = (
            (("checkout", "--", CONFIG_PATH), FETCH_TIMEOUT),
            (("pull", "--ff-only"), PULL_TIMEOUT),
        )
        for args, timeout in steps:
            result = self._run(args, timeout=timeout)
            if result is None:
                return False
            if result.returncode != 0:
                logger.error("Update step %s failed: %s", args[0], result.stderr.strip())
                return False
        logger.info("Updated to the latest version")
        return True

    @staticmethod
    def _run(args, timeout: int = FETCH_TIMEOUT):
        """None when git itself could not be run - no network, no git, no patience."""
        try:
            return _git(*args, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as error:
            logger.info("git %s failed (%s)", args[0], error)
            return None
