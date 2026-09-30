"""Official weather warnings from the MeteoAlarm feeds.

MeteoAlarm publishes what the national services issue - MeteoSchweiz and Meteo-France
for the places we travel to. The open Atom feeds carry one entry per warning and region
and link the full CAP document with the actual text.

Two things the feeds do not have, which shape everything here:

- **No geometry.** Neither the Atom entry nor the CAP document carries a polygon, only
  a NUTS3 code and an area name. A warning can therefore only be matched to a place
  whose region is known in advance - which is why `Location.regions` exists and why the
  phone position, which moves, gets no warnings.
- **No single document per region.** One CAP covers several areas at once, so the
  details are fetched once per warning and shared.

The details are fetched while the connection is there rather than when the window is
opened, so a warning read in the morning can still be opened in the evening.
"""

from __future__ import annotations

import logging
import urllib.request
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)

FEEDS = {
    "CH": "https://feeds.meteoalarm.org/feeds/meteoalarm-legacy-atom-switzerland",
    "FR": "https://feeds.meteoalarm.org/feeds/meteoalarm-legacy-atom-france",
}
HTTP_TIMEOUT = 8
MAX_DETAIL_FETCHES = 12  # a lid on the extra requests when a whole country is in alarm
LANGUAGE_ORDER = ("de", "fr", "en")  # what to show when a CAP carries several


# MeteoAlarm severities, lowest first. The colours are the ones MeteoAlarm uses itself.
SEVERITIES = ("Minor", "Moderate", "Severe", "Extreme")
SEVERITY_COLORS = {
    "Minor": "#f6c744",
    "Moderate": "#f6c744",
    "Severe": "#ef6c00",
    "Extreme": "#c62828",
}
DEFAULT_SEVERITY_COLOR = "#f6c744"


@dataclass
class WeatherWarning:
    event: str
    severity: str
    area: str
    onset: str
    expires: str
    link: str = ""
    headline: str = ""
    description: str = ""
    instruction: str = ""
    sender: str = ""

    def to_dict(self) -> dict:
        return {
            "event": self.event,
            "severity": self.severity,
            "area": self.area,
            "onset": self.onset,
            "expires": self.expires,
            "link": self.link,
            "headline": self.headline,
            "description": self.description,
            "instruction": self.instruction,
            "sender": self.sender,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WeatherWarning":
        return cls(
            event=str(data.get("event", "")),
            severity=str(data.get("severity", "")),
            area=str(data.get("area", "")),
            onset=str(data.get("onset", "")),
            expires=str(data.get("expires", "")),
            link=str(data.get("link", "")),
            headline=str(data.get("headline", "")),
            description=str(data.get("description", "")),
            instruction=str(data.get("instruction", "")),
            sender=str(data.get("sender", "")),
        )

    @property
    def color(self) -> str:
        return SEVERITY_COLORS.get(self.severity, DEFAULT_SEVERITY_COLOR)

    @property
    def rank(self) -> int:
        """For picking the worst warning of a day."""
        return SEVERITIES.index(self.severity) if self.severity in SEVERITIES else 0

    def covers(self, day: str) -> bool:
        """Whether the warning is in force on `day` (an ISO date)."""
        first, last = _day_of(self.onset), _day_of(self.expires)
        if first is None or last is None:
            return False
        return first <= day <= last

    @property
    def days(self) -> list:
        """Every ISO date the warning touches, so a column can look itself up."""
        first, last = _day_of(self.onset), _day_of(self.expires)
        if first is None or last is None:
            return []
        start = date.fromisoformat(first)
        end = date.fromisoformat(last)
        span = (end - start).days
        return [(start + timedelta(days=offset)).isoformat() for offset in range(span + 1)]


def _day_of(stamp: str):
    """The ISO date of a CAP timestamp, or None when it cannot be read."""
    try:
        return datetime.fromisoformat(stamp).date().isoformat()
    except ValueError:
        return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element, name: str) -> str:
    """By local name: the feed mixes prefixed cap: elements with unprefixed ones that
    inherit the Atom namespace, so matching the full tag finds only half of them."""
    for child in element.iter():
        if child is not element and _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "BedLiftControl/1.0"})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        return response.read()


def _region_keys(entry) -> set:
    """The identifiers an entry can be matched on: NUTS codes and the area name."""
    keys = {_text(entry, "areaDesc").lower()}
    for child in entry.iter():
        if _local(child.tag) == "value" and child.text:
            keys.add(child.text.strip().lower())
    return {key for key in keys if key}


def _cap_link(entry) -> str:
    for link in entry.iter():
        if _local(link.tag) != "link":
            continue
        if link.get("type") == "application/cap+xml":
            return link.get("href", "")
    return ""


def parse_feed(payload: bytes) -> list:
    """Every entry of one country feed, as (region keys, warning) pairs."""
    root = ElementTree.fromstring(payload)
    entries = []
    for entry in root.iter():
        if _local(entry.tag) != "entry":
            continue
        warning = WeatherWarning(
            event=_text(entry, "event"),
            severity=_text(entry, "severity"),
            area=_text(entry, "areaDesc"),
            onset=_text(entry, "onset") or _text(entry, "effective"),
            expires=_text(entry, "expires"),
            link=_cap_link(entry),
        )
        entries.append((_region_keys(entry), warning))
    return entries


def _pick_info(root):
    """The CAP block in the most useful language, or the first one."""
    blocks = [node for node in root.iter() if _local(node.tag) == "info"]
    for language in LANGUAGE_ORDER:
        for block in blocks:
            if _text(block, "language").lower().startswith(language):
                return block
    return blocks[0] if blocks else None


def add_details(warning: WeatherWarning) -> bool:
    """Fill in headline, description and instruction from the linked CAP document."""
    if not warning.link:
        return False
    try:
        root = ElementTree.fromstring(_fetch(warning.link))
    except Exception:  # network boundary: a warning without its text is still a warning
        logger.info("Could not read the warning details from %s", warning.link, exc_info=True)
        return False
    info = _pick_info(root)
    if info is None:
        return False
    warning.headline = _text(info, "headline") or warning.headline
    warning.description = _text(info, "description")
    warning.instruction = _text(info, "instruction")
    warning.sender = _text(info, "senderName")
    return True


def fetch_warnings(locations) -> dict:
    """Warnings per location key, for the locations that know their region.

    Raises nothing: a country whose feed cannot be read simply contributes nothing, and
    the caller keeps whatever it had.
    """
    wanted = {place.key: {region.lower() for region in place.regions}
              for place in locations if place.regions}
    if not wanted:
        return {}
    found = {key: [] for key in wanted}
    unmatched = set()
    for country, url in FEEDS.items():
        try:
            entries = parse_feed(_fetch(url))
        except Exception:
            logger.info("Could not read the %s warning feed", country, exc_info=True)
            continue
        for keys, warning in entries:
            matched = [key for key, regions in wanted.items() if keys & regions]
            for key in matched:
                found[key].append(warning)
            if not matched:
                unmatched |= keys
    if unmatched:
        # the Swiss feed was empty while this was written, so its region identifiers
        # could not be verified - this line is how they show up the first time
        logger.debug("Warning regions we do not map: %s", sorted(unmatched))
    _load_details(found)
    for key, warnings in found.items():
        if warnings:
            logger.info("%s: %s warning(s) in force", key, len(warnings))
    return found


def _load_details(found: dict) -> None:
    """One fetch per distinct CAP document, capped, shared by every location using it."""
    cache = {}
    budget = MAX_DETAIL_FETCHES
    for warnings in found.values():
        for warning in warnings:
            if warning.link in cache:
                _copy_details(cache[warning.link], warning)
            elif budget > 0:
                budget -= 1
                if add_details(warning):
                    cache[warning.link] = warning


def _copy_details(source: WeatherWarning, target: WeatherWarning) -> None:
    target.headline = source.headline
    target.description = source.description
    target.instruction = source.instruction
    target.sender = source.sender
