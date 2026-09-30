"""Is there internet right now?

The van is offline most of the time and online the moment the phone hotspot comes
within reach. Asking the weather API over and over to find that out means a DNS
lookup, a TLS handshake and a JSON body every time. A TCP connect answers the same
question for a few bytes, so that is what is polled while offline - the real request
only follows once this says yes.
"""

import logging
import socket

logger = logging.getLogger(__name__)

PROBE_HOST = "api.open-meteo.com"
PROBE_PORT = 443
PROBE_TIMEOUT = 3


def is_online(host: str = PROBE_HOST, port: int = PROBE_PORT,
              timeout: float = PROBE_TIMEOUT) -> bool:
    """Whether `host` can be reached. Name resolution is part of the answer: a hotspot
    that is associated but has no route resolves nothing."""
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False
