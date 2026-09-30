"""Test bootstrap.

The application imports ``customtkinter`` and ``RPi.GPIO`` and builds the GUI at
import time. Neither is available (or wanted) in a headless test run, so we replace
them with mocks *before* the application modules are imported. Mocks are forced so
the tests never open a real window or touch GPIO pins, even on the Pi itself.
"""

import sys
from unittest.mock import MagicMock

import pytest

sys.modules["RPi"] = MagicMock()
sys.modules["RPi.GPIO"] = MagicMock()
sys.modules["customtkinter"] = MagicMock()


@pytest.fixture(autouse=True)
def no_warning_feeds(monkeypatch):
    """No test reaches out to the MeteoAlarm feeds - the network is not a fixture.

    Patched on the module, which is how weather.py calls it, so a test that wants
    warnings can put its own answer in the same place.
    """
    from bedliftcontrol import alerts

    monkeypatch.setattr(alerts, "fetch_warnings", lambda locations: {})
    monkeypatch.setattr(alerts, "add_details", lambda warning: False)
