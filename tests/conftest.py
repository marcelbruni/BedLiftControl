"""Test bootstrap.

The application imports ``customtkinter`` and ``RPi.GPIO`` and builds the GUI at
import time. Neither is available (or wanted) in a headless test run, so we replace
them with mocks *before* the application modules are imported. Mocks are forced so
the tests never open a real window or touch GPIO pins, even on the Pi itself.
"""

import sys
from unittest.mock import MagicMock

sys.modules["RPi"] = MagicMock()
sys.modules["RPi.GPIO"] = MagicMock()
sys.modules["customtkinter"] = MagicMock()
