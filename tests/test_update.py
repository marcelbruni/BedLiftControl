"""Tests for the update check.

git is replaced by a stub that records the calls, so nothing touches the network or
the working tree.
"""

from unittest.mock import MagicMock

import pytest

from bedliftcontrol import update as update_module
from bedliftcontrol.update import REPO_DIR, UpdateChecker


class GitStub:
    """Answers each git call in turn; records what it was asked to do."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []
        self.env = None

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        self.env = kwargs.get("env")
        result = self.results.pop(0) if self.results else ok()
        if isinstance(result, Exception):
            raise result
        return result


def ok(stdout=""):
    return MagicMock(returncode=0, stdout=stdout, stderr="")


def failed(stderr="boom"):
    return MagicMock(returncode=1, stdout="", stderr=stderr)


@pytest.fixture
def git(monkeypatch):
    stub = GitStub()
    monkeypatch.setattr(update_module.subprocess, "run", stub)
    return stub


@pytest.fixture
def checker():
    return UpdateChecker()


class TestCheck:
    def test_it_fetches_before_comparing(self, checker, git):
        git.results = [ok(), ok("0")]
        checker.check_once()
        assert git.calls[0][3] == "fetch"
        assert git.calls[1][3] == "rev-list"

    def test_it_works_in_the_project_directory(self, checker, git):
        git.results = [ok(), ok("0")]
        checker.check_once()
        assert git.calls[0][:3] == ["git", "-C", REPO_DIR]

    def test_it_never_asks_for_credentials(self, checker, git):
        """There is no keyboard: a prompting git would hang the thread forever."""
        git.results = [ok(), ok("0")]
        checker.check_once()
        assert git.env["GIT_TERMINAL_PROMPT"] == "0"

    def test_it_counts_the_commits_behind(self, checker, git):
        git.results = [ok(), ok("3\n")]
        assert checker.check_once() is True
        assert checker.pending == 3
        assert checker.update_available is True

    def test_being_up_to_date_is_not_an_update(self, checker, git):
        git.results = [ok(), ok("0\n")]
        checker.check_once()
        assert checker.update_available is False

    def test_an_empty_answer_counts_as_none(self, checker, git):
        git.results = [ok(), ok("")]
        checker.check_once()
        assert checker.pending == 0

    def test_a_failed_fetch_reports_offline(self, checker, git):
        git.results = [failed("could not resolve host")]
        assert checker.check_once() is False

    def test_a_failed_fetch_leaves_the_last_answer_alone(self, checker, git):
        git.results = [ok(), ok("2")]
        checker.check_once()
        git.results = [failed()]
        checker.check_once()
        assert checker.pending == 2, "offline is not the same as up to date"

    def test_a_failed_comparison_reports_offline(self, checker, git):
        git.results = [ok(), failed("no upstream")]
        assert checker.check_once() is False

    def test_a_timeout_is_not_an_error(self, checker, git, monkeypatch):
        import subprocess

        git.results = [subprocess.TimeoutExpired("git", 30)]
        assert checker.check_once() is False

    def test_a_missing_git_is_not_an_error(self, checker, git):
        git.results = [FileNotFoundError("git")]
        assert checker.check_once() is False


class TestApply:
    def test_it_clears_the_config_then_pulls(self, checker, git):
        """The running app keeps writing the checked-in config, so a pull is refused
        until that copy is out of the way."""
        checker.apply()
        assert git.calls[0][3:] == ["checkout", "--", "data/config.json"]
        assert git.calls[1][3:] == ["pull", "--ff-only"]

    def test_it_reports_success(self, checker, git):
        assert checker.apply() is True

    def test_the_button_goes_away_afterwards(self, checker, git):
        git.results = [ok(), ok("2")]
        checker.check_once()
        git.results = []
        checker.apply()
        assert checker.update_available is False

    def test_a_failed_checkout_stops_before_pulling(self, checker, git):
        git.results = [failed()]
        assert checker.apply() is False
        assert len(git.calls) == 1

    def test_a_failed_pull_reports_failure(self, checker, git):
        git.results = [ok(), failed("would be overwritten")]
        assert checker.apply() is False

    def test_a_failed_update_keeps_the_button(self, checker, git):
        git.results = [ok(), ok("2")]
        checker.check_once()
        git.results = [ok(), failed()]
        checker.apply()
        assert checker.update_available is True

    def test_a_crashing_git_is_caught(self, checker, git):
        git.results = [OSError("no such file")]
        assert checker.apply() is False


class TestLoop:
    @staticmethod
    def one_round(checker, monkeypatch, reached):
        """Record the wait of a single round, then let the loop end."""
        waits = []

        def wait(seconds):
            waits.append(seconds)
            checker._stop.set()
            return True

        monkeypatch.setattr(checker, "check_once", lambda: reached)
        monkeypatch.setattr(checker._stop, "wait", wait)
        checker._loop()
        return waits

    def test_it_waits_the_full_interval_when_it_reached_the_remote(self, checker, monkeypatch):
        assert self.one_round(checker, monkeypatch, reached=True) == [checker.interval]

    def test_it_retries_sooner_while_offline(self, checker, monkeypatch):
        """So the button turns up shortly after the hotspot comes back."""
        assert self.one_round(checker, monkeypatch, reached=False) == [checker.retry_interval]

    def test_stopping_ends_the_loop(self, checker, monkeypatch):
        monkeypatch.setattr(checker, "check_once", lambda: True)
        checker._stop.set()
        checker._loop()  # must return at once

    def test_start_is_idempotent(self, checker, monkeypatch):
        monkeypatch.setattr(checker, "check_once", lambda: True)
        checker.start()
        first = checker._thread
        checker.start()
        assert checker._thread is first
        checker.stop()
