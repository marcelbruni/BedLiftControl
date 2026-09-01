"""Test bootstrap.

The application module imports ``guizero`` and ``RPi.GPIO`` and builds the GUI at
import time. Neither is available off a Raspberry Pi, so we replace them with mocks
*before* the application module is imported. Mocks are forced (not conditional) so
the tests never touch a real GUI or GPIO pins, even when run on the Pi itself.
"""

import sys
from unittest.mock import MagicMock

sys.modules["RPi"] = MagicMock()
sys.modules["RPi.GPIO"] = MagicMock()
sys.modules["guizero"] = MagicMock()
