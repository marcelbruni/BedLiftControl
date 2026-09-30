"""Tests for the update button.

git is replaced by a stub that records the calls, so nothing touches the network or
the working tree.
"""

from unittest.mock import MagicMock

import pytest

from bedliftcontrol import update as update_module
from bedliftcontrol.update import FAILED, REPO_DIR, UPDATED, UP_TO_DATE, Updater


class GitStub:
    """Answers each git call in turn; records what it was asked to do."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []
        self.kwargs = {}
        self.env = None

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        self.kwargs = kwargs
        self.env = kwargs.get("env")
        result = self.results.pop(0) if self.results else ok()
        if isinstance(result, Exception):
            raise result
        return result

    @property
    def commands(self):
        return [call[3] for call in self.calls]


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
def updater():
    return Updater()


class TestInstall:
    def test_it_looks_before_it_pulls(self, updater, git):
        git.results = [ok(), ok("2")]
        updater.install()
        assert git.commands == ["fetch", "rev-list", "checkout", "pull"]

    def test_it_reports_the_installation(self, updater, git):
        git.results = [ok(), ok("2")]
        assert updater.install() == UPDATED

    def test_nothing_new_means_nothing_is_pulled(self, updater, git):
        git.results = [ok(), ok("0\n")]
        assert updater.install() == UP_TO_DATE
        assert git.commands == ["fetch", "rev-list"]

    def test_an_empty_answer_counts_as_nothing_new(self, updater, git):
        git.results = [ok(), ok("")]
        assert updater.install() == UP_TO_DATE

    def test_it_works_in_the_project_directory(self, updater, git):
        git.results = [ok(), ok("0")]
        updater.install()
        assert git.calls[0][:3] == ["git", "-C", REPO_DIR]

    def test_it_never_asks_for_credentials(self, updater, git):
        """There is no keyboard: a prompting git would hang the thread forever."""
        git.results = [ok(), ok("0")]
        updater.install()
        assert git.env["GIT_TERMINAL_PROMPT"] == "0"

    def test_it_clears_the_config_before_pulling(self, updater, git):
        """The running app keeps writing the checked-in config, so a pull is refused
        until that copy is out of the way."""
        git.results = [ok(), ok("1")]
        updater.install()
        assert git.calls[2][3:] == ["checkout", "--", "data/config.json"]
        assert git.calls[3][3:] == ["pull", "--ff-only"]


class TestWhenItCannotBeDone:
    def test_being_offline_is_not_being_up_to_date(self, updater, git):
        git.results = [failed("could not resolve host")]
        assert updater.install() == FAILED

    def test_a_missing_upstream_fails(self, updater, git):
        git.results = [ok(), failed("no upstream configured")]
        assert updater.install() == FAILED

    def test_a_failed_checkout_stops_before_pulling(self, updater, git):
        git.results = [ok(), ok("1"), failed()]
        assert updater.install() == FAILED
        assert "pull" not in git.commands

    def test_a_failed_pull_is_reported(self, updater, git):
        git.results = [ok(), ok("1"), ok(), failed("would be overwritten")]
        assert updater.install() == FAILED

    def test_a_timeout_is_caught(self, updater, git):
        import subprocess

        git.results = [subprocess.TimeoutExpired("git", 30)]
        assert updater.install() == FAILED

    def test_a_missing_git_is_caught(self, updater, git):
        git.results = [FileNotFoundError("git")]
        assert updater.install() == FAILED

    def test_a_crash_while_pulling_is_caught(self, updater, git):
        git.results = [ok(), ok("1"), OSError("no such file")]
        assert updater.install() == FAILED


class TestVersion:
    def test_it_reports_the_checked_out_commit(self, updater, git):
        git.results = [ok("e28a2d1 · 29.09.2026 21:52\n")]
        assert updater.version() == "e28a2d1 · 29.09.2026 21:52"

    def test_it_reads_only_the_last_commit(self, updater, git):
        git.results = [ok("x")]
        updater.version()
        assert git.calls[0][3:5] == ["log", "-1"]

    def test_it_asks_nothing_of_the_network(self, updater, git):
        """Opening the settings must not wait for GitHub."""
        git.results = [ok("x")]
        updater.version()
        assert git.commands == ["log"]

    def test_a_checkout_without_git_says_so(self, updater, git):
        git.results = [failed("not a git repository")]
        assert updater.version() == update_module.UNKNOWN_VERSION

    def test_a_missing_git_says_so(self, updater, git):
        git.results = [FileNotFoundError("git")]
        assert updater.version() == update_module.UNKNOWN_VERSION

    def test_an_empty_answer_says_so(self, updater, git):
        git.results = [ok("  \n")]
        assert updater.version() == update_module.UNKNOWN_VERSION

    def test_git_is_read_as_utf_8(self, updater, git):
        """The Windows locale codepage turns the separator into two characters."""
        git.results = [ok("x")]
        updater.version()
        assert git.kwargs["encoding"] == "utf-8"
