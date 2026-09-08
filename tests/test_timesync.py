"""Tests for the internet time sync.

No network is touched: urlopen is replaced by a fake that returns a Date header, so the
offset arithmetic, the offline fallback and the system-clock guards are all testable.
"""

from datetime import datetime, timedelta, timezone

import pytest

from bedliftcontrol import timesync as timesync_module
from bedliftcontrol.timesync import (
    HEADER_RESOLUTION,
    SYSTEM_CLOCK_THRESHOLD,
    TimeSync,
    fetch_internet_utc,
    set_system_clock,
)


class FakeResponse:
    def __init__(self, date_header):
        self.headers = {"Date": date_header}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def fake_urlopen(date_header):
    def opener(_request, timeout=None):
        return FakeResponse(date_header)

    return opener


@pytest.fixture
def offline(monkeypatch):
    def boom(_request, timeout=None):
        raise OSError("no route to host")

    monkeypatch.setattr(timesync_module.urllib.request, "urlopen", boom)


class TestFetchInternetUtc:
    def test_parses_the_date_header(self, monkeypatch):
        monkeypatch.setattr(
            timesync_module.urllib.request, "urlopen",
            fake_urlopen("Tue, 08 Sep 2026 11:42:46 GMT"),
        )
        server, local = fetch_internet_utc()
        assert server == datetime(2026, 9, 8, 11, 42, 46, tzinfo=timezone.utc) + HEADER_RESOLUTION
        assert local.tzinfo == timezone.utc

    def test_adds_half_a_second_for_the_header_resolution(self, monkeypatch):
        """The header is truncated to the second, so the real instant is later."""
        monkeypatch.setattr(
            timesync_module.urllib.request, "urlopen",
            fake_urlopen("Tue, 08 Sep 2026 11:42:46 GMT"),
        )
        server, _ = fetch_internet_utc()
        assert server.microsecond == 500000

    def test_missing_header_raises(self, monkeypatch):
        monkeypatch.setattr(timesync_module.urllib.request, "urlopen", fake_urlopen(None))
        with pytest.raises(ValueError):
            fetch_internet_utc()

    def test_local_reference_is_the_round_trip_midpoint(self, monkeypatch):
        monkeypatch.setattr(
            timesync_module.urllib.request, "urlopen",
            fake_urlopen("Tue, 08 Sep 2026 11:42:46 GMT"),
        )
        before = datetime.now(timezone.utc)
        _, local = fetch_internet_utc()
        after = datetime.now(timezone.utc)
        assert before <= local <= after


class TestNow:
    def test_without_a_sync_it_is_the_bare_machine_clock(self, monkeypatch):
        machine = datetime(2026, 9, 8, 13, 0, 0)
        monkeypatch.setattr(timesync_module.clock, "now", lambda: machine)
        sync = TimeSync()
        assert sync.now() == machine
        assert sync.synced is False

    def test_applies_the_measured_offset(self, monkeypatch):
        machine = datetime(2026, 9, 8, 13, 0, 0)
        monkeypatch.setattr(timesync_module.clock, "now", lambda: machine)
        sync = TimeSync()
        sync.offset = timedelta(minutes=7, seconds=30)
        assert sync.now() == datetime(2026, 9, 8, 13, 7, 30)

    def test_a_machine_clock_running_ahead_is_pulled_back(self, monkeypatch):
        monkeypatch.setattr(timesync_module.clock, "now", lambda: datetime(2026, 9, 8, 13, 5))
        sync = TimeSync()
        sync.offset = timedelta(minutes=-5)
        assert sync.now() == datetime(2026, 9, 8, 13, 0)


class TestRefreshOnce:
    def test_measures_and_stores_the_offset(self, monkeypatch):
        monkeypatch.setattr(
            timesync_module.urllib.request, "urlopen",
            fake_urlopen("Tue, 08 Sep 2026 11:42:46 GMT"),
        )
        monkeypatch.setattr(timesync_module, "set_system_clock", lambda offset: False)
        sync = TimeSync()
        assert sync.refresh_once() is True
        assert sync.synced is True
        assert sync.last_sync is not None

    def test_offline_keeps_the_previous_offset(self, offline):
        sync = TimeSync()
        sync.offset = timedelta(seconds=42)
        assert sync.refresh_once() is False
        assert sync.offset == timedelta(seconds=42), "an offline poll must not reset the offset"

    def test_offline_never_raises(self, offline):
        TimeSync().refresh_once()  # must not raise


class TestSystemClock:
    def test_not_attempted_for_a_small_offset(self, monkeypatch):
        monkeypatch.setattr(
            timesync_module.urllib.request, "urlopen",
            fake_urlopen("Tue, 08 Sep 2026 11:42:46 GMT"),
        )
        attempts = []
        monkeypatch.setattr(timesync_module, "set_system_clock", lambda offset: attempts.append(offset))
        sync = TimeSync()
        # the fake header is "now" give or take, so the offset stays tiny
        sync.refresh_once()
        assert not attempts or all(abs(o) >= SYSTEM_CLOCK_THRESHOLD for o in attempts)

    def test_offset_is_cleared_once_the_system_clock_carries_the_correction(self, monkeypatch):
        """Otherwise the same correction would be applied twice."""
        monkeypatch.setattr(
            timesync_module.urllib.request, "urlopen",
            fake_urlopen("Tue, 08 Sep 2036 11:42:46 GMT"),  # ten years off -> way over the threshold
        )
        monkeypatch.setattr(timesync_module, "set_system_clock", lambda offset: True)
        sync = TimeSync()
        sync.refresh_once()
        assert sync.offset == timedelta(0)

    def test_offset_is_kept_when_the_system_clock_could_not_be_set(self, monkeypatch):
        monkeypatch.setattr(
            timesync_module.urllib.request, "urlopen",
            fake_urlopen("Tue, 08 Sep 2036 11:42:46 GMT"),
        )
        monkeypatch.setattr(timesync_module, "set_system_clock", lambda offset: False)
        sync = TimeSync()
        sync.refresh_once()
        assert sync.offset > timedelta(days=3000), "the app clock must still correct itself"

    def test_disabled_means_no_attempt(self, monkeypatch):
        monkeypatch.setattr(
            timesync_module.urllib.request, "urlopen",
            fake_urlopen("Tue, 08 Sep 2036 11:42:46 GMT"),
        )
        attempts = []
        monkeypatch.setattr(timesync_module, "set_system_clock", lambda offset: attempts.append(offset))
        TimeSync(adjust_system_clock=False).refresh_once()
        assert not attempts

    def test_skipped_on_windows(self, monkeypatch):
        monkeypatch.setattr(timesync_module.sys, "platform", "win32")
        assert set_system_clock(timedelta(hours=1)) is False

    def test_failure_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setattr(timesync_module.sys, "platform", "linux")

        def boom(*_args, **_kwargs):
            raise OSError("sudo not found")

        monkeypatch.setattr(timesync_module.subprocess, "run", boom)
        assert set_system_clock(timedelta(hours=1)) is False

    def test_non_zero_exit_is_a_failure(self, monkeypatch):
        monkeypatch.setattr(timesync_module.sys, "platform", "linux")

        class Result:
            returncode = 1
            stderr = "sudo: a password is required"

        monkeypatch.setattr(timesync_module.subprocess, "run", lambda *a, **k: Result())
        assert set_system_clock(timedelta(hours=1)) is False

    def test_success_is_reported(self, monkeypatch):
        monkeypatch.setattr(timesync_module.sys, "platform", "linux")

        class Result:
            returncode = 0
            stderr = ""

        recorded = {}

        def run(command, **_kwargs):
            recorded["command"] = command
            return Result()

        monkeypatch.setattr(timesync_module.subprocess, "run", run)
        assert set_system_clock(timedelta(hours=1)) is True
        assert recorded["command"][:3] == ["sudo", "-n", "date"]
        assert "-u" in recorded["command"], "the stamp is UTC, so date must be told so"
