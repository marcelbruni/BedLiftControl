"""Tests for the reachability probe. No socket is ever really opened."""

import socket

import pytest

from bedliftcontrol import connectivity


@pytest.fixture(autouse=True)
def no_reachability_probe():
    """Overrides the global stub: this module tests the real probe, with the socket
    replaced instead - nothing here opens a connection either."""
    yield


@pytest.fixture
def probe(monkeypatch):
    """Records what was connected to; the answer is set per test."""
    calls = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def connect(address, timeout=None):
        calls.append((address, timeout))
        if isinstance(connect.answer, Exception):
            raise connect.answer
        return Connection()

    connect.answer = None
    monkeypatch.setattr(connectivity.socket, "create_connection", connect)
    return connect, calls


class TestIsOnline:
    def test_a_reachable_host_means_online(self, probe):
        assert connectivity.is_online() is True

    def test_a_refused_connection_means_offline(self, probe):
        connect, _ = probe
        connect.answer = ConnectionRefusedError()
        assert connectivity.is_online() is False

    def test_an_unresolvable_name_means_offline(self, probe):
        """A hotspot that is associated but has no route resolves nothing."""
        connect, _ = probe
        connect.answer = socket.gaierror("name resolution failed")
        assert connectivity.is_online() is False

    def test_a_timeout_means_offline(self, probe):
        connect, _ = probe
        connect.answer = socket.timeout()
        assert connectivity.is_online() is False

    def test_no_route_means_offline(self, probe):
        connect, _ = probe
        connect.answer = OSError("network is unreachable")
        assert connectivity.is_online() is False

    def test_it_asks_the_weather_host(self, probe):
        _, calls = probe
        connectivity.is_online()
        assert calls[0][0] == (connectivity.PROBE_HOST, connectivity.PROBE_PORT)

    def test_it_does_not_hang(self, probe):
        """Without a timeout an unreachable host blocks the thread for minutes."""
        _, calls = probe
        connectivity.is_online()
        assert calls[0][1] == connectivity.PROBE_TIMEOUT

    def test_it_stays_a_plain_connect(self):
        """The whole point is that it costs almost nothing - no HTTP, no payload."""
        import inspect

        assert "urllib" not in inspect.getsource(connectivity)
