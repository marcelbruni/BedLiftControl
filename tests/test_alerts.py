"""Tests for the MeteoAlarm warning feed.

The sample feed is the real structure, shortened: prefixed cap: elements next to
unprefixed ones that inherit the Atom namespace - the trap the first parser fell into.
"""

from dataclasses import dataclass

import pytest

from bedliftcontrol import alerts
from bedliftcontrol.alerts import WeatherWarning

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:cap="urn:oasis:names:tc:emergency:cap:1.2">
  <entry>
    <cap:geocode><valueName>NUTS3</valueName><value>FR718</value></cap:geocode>
    <cap:areaDesc>Haute-Savoie</cap:areaDesc>
    <cap:event>Moderate wind warning</cap:event>
    <cap:severity>Moderate</cap:severity>
    <cap:onset>2026-09-30T22:00:00+00:00</cap:onset>
    <cap:expires>2026-10-01T22:00:00+00:00</cap:expires>
    <link type="application/cap+xml" href="https://example.invalid/cap/1"/>
    <title>Yellow Wind Warning issued for France - Haute-Savoie</title>
  </entry>
  <entry>
    <cap:geocode><valueName>NUTS3</valueName><value>CH021</value></cap:geocode>
    <cap:areaDesc>Bern</cap:areaDesc>
    <cap:event>Severe thunderstorm warning</cap:event>
    <cap:severity>Severe</cap:severity>
    <cap:onset>2026-09-30T12:00:00+00:00</cap:onset>
    <cap:expires>2026-09-30T20:00:00+00:00</cap:expires>
    <link type="application/cap+xml" href="https://example.invalid/cap/2"/>
    <title>Orange Thunderstorm Warning issued for Switzerland - Bern</title>
  </entry>
  <entry>
    <cap:geocode><valueName>NUTS3</valueName><value>FR101</value></cap:geocode>
    <cap:areaDesc>Paris</cap:areaDesc>
    <cap:event>Minor rain warning</cap:event>
    <cap:severity>Minor</cap:severity>
    <cap:onset>2026-09-30T06:00:00+00:00</cap:onset>
    <cap:expires>2026-09-30T18:00:00+00:00</cap:expires>
    <link type="application/cap+xml" href="https://example.invalid/cap/3"/>
    <title>Yellow Rain Warning issued for France - Paris</title>
  </entry>
</feed>"""

CAP = """<?xml version="1.0" encoding="UTF-8"?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <info>
    <language>en-GB</language>
    <headline>Wind warning</headline>
    <description>English text</description>
    <senderName>METEO-FRANCE</senderName>
  </info>
  <info>
    <language>fr-FR</language>
    <headline>Vigilance jaune vent</headline>
    <description>Des rafales jusqu a 90 km/h.</description>
    <instruction>Soyez prudents.</instruction>
    <senderName>METEO-FRANCE</senderName>
  </info>
</alert>"""


@pytest.fixture(autouse=True)
def no_warning_feeds():
    """Overrides the global stub: this module tests the real fetcher, with `_fetch`
    replaced instead - nothing here reaches the network either."""
    yield


@dataclass(frozen=True)
class Place:
    key: str
    regions: tuple = ()


@pytest.fixture
def feeds(monkeypatch):
    """One feed for both countries, and a CAP document behind every link."""
    fetched = []

    def fake_fetch(url):
        fetched.append(url)
        return CAP.encode("utf-8") if "/cap/" in url else FEED.encode("utf-8")

    monkeypatch.setattr(alerts, "_fetch", fake_fetch)
    return fetched


class TestParsing:
    def test_it_reads_every_entry(self):
        assert len(alerts.parse_feed(FEED.encode("utf-8"))) == 3

    def test_the_unprefixed_geocode_is_found(self):
        """<value> inherits the Atom namespace, not the cap: one - matching the full
        tag name finds nothing at all."""
        keys, _ = alerts.parse_feed(FEED.encode("utf-8"))[0]
        assert "fr718" in keys

    def test_the_area_name_is_a_key_too(self):
        keys, _ = alerts.parse_feed(FEED.encode("utf-8"))[0]
        assert "haute-savoie" in keys

    def test_it_reads_the_warning_itself(self):
        _, warning = alerts.parse_feed(FEED.encode("utf-8"))[1]
        assert warning.event == "Severe thunderstorm warning"
        assert warning.severity == "Severe"
        assert warning.area == "Bern"
        assert warning.link == "https://example.invalid/cap/2"

    def test_a_broken_feed_says_it_could_not_find_out(self, monkeypatch):
        """None, not an empty answer: otherwise a hiccup would clear real warnings."""
        monkeypatch.setattr(alerts, "_fetch", lambda url: b"<not xml")
        assert alerts.fetch_warnings([Place("x", ("FR718",))]) is None

    def test_one_readable_feed_is_enough_for_an_answer(self, monkeypatch):
        """Half the countries unreachable still tells us about the other half."""
        def half_dead(url):
            if "france" in url:
                return FEED.encode("utf-8")
            raise OSError("no route to host")

        monkeypatch.setattr(alerts, "_fetch", half_dead)
        found = alerts.fetch_warnings([Place("chatel", ("FR718",))])
        assert found is not None and found["chatel"]


class TestMatching:
    def test_by_region_code(self, feeds):
        found = alerts.fetch_warnings([Place("chatel", ("FR718",))])
        assert [w.area for w in found["chatel"]] == ["Haute-Savoie", "Haute-Savoie"]

    def test_by_area_name(self, feeds):
        """The Swiss identifiers could not be verified, so names match as well."""
        found = alerts.fetch_warnings([Place("hoefen", ("bern",))])
        assert found["hoefen"] and found["hoefen"][0].area == "Bern"

    def test_matching_ignores_case(self, feeds):
        found = alerts.fetch_warnings([Place("chatel", ("fr718", "HAUTE-SAVOIE"))])
        assert found["chatel"]

    def test_a_place_without_regions_gets_an_empty_answer(self, feeds):
        """The phone position moves, so no region can be written down for it - but it
        has to be in the answer, or a warning once put there would never go away."""
        assert alerts.fetch_warnings([Place("phone")]) == {"phone": []}

    def test_every_place_is_in_the_answer(self, feeds):
        """The caller replaces its whole set with this one."""
        places = [Place("chatel", ("FR718",)), Place("phone"), Place("lacure", ("FR432",))]
        assert set(alerts.fetch_warnings(places)) == {"chatel", "phone", "lacure"}

    def test_other_regions_do_not_leak_in(self, feeds):
        found = alerts.fetch_warnings([Place("chatel", ("FR718",))])
        assert all("Paris" not in warning.area for warning in found["chatel"])

    def test_two_places_can_share_a_region(self, feeds):
        found = alerts.fetch_warnings([Place("hoefen", ("CH021",)),
                                       Place("schilthorn", ("CH021",))])
        assert found["hoefen"] and found["schilthorn"]


class TestDetails:
    def test_the_text_is_fetched(self, feeds):
        found = alerts.fetch_warnings([Place("chatel", ("FR718",))])
        assert found["chatel"][0].description.startswith("Des rafales")

    def test_the_preferred_language_wins(self, feeds):
        """German first, then French - English only when nothing else is offered."""
        found = alerts.fetch_warnings([Place("chatel", ("FR718",))])
        assert found["chatel"][0].headline == "Vigilance jaune vent"

    def test_the_instruction_comes_along(self, feeds):
        found = alerts.fetch_warnings([Place("chatel", ("FR718",))])
        assert found["chatel"][0].instruction == "Soyez prudents."

    def test_one_document_is_fetched_once(self, feeds):
        """Two places in the same region share the warning and its text."""
        alerts.fetch_warnings([Place("a", ("CH021",)), Place("b", ("bern",))])
        assert feeds.count("https://example.invalid/cap/2") == 1

    def test_a_failing_detail_fetch_keeps_the_warning(self, monkeypatch):
        def fetch(url):
            if "/cap/" in url:
                raise OSError("no route to host")
            return FEED.encode("utf-8")

        monkeypatch.setattr(alerts, "_fetch", fetch)
        found = alerts.fetch_warnings([Place("chatel", ("FR718",))])
        assert found["chatel"] and found["chatel"][0].description == ""

    def test_the_number_of_detail_fetches_is_capped(self, monkeypatch):
        """A country in alarm must not turn into a hundred requests."""
        monkeypatch.setattr(alerts, "MAX_DETAIL_FETCHES", 1)
        calls = []

        def fetch(url):
            calls.append(url)
            return CAP.encode("utf-8") if "/cap/" in url else FEED.encode("utf-8")

        monkeypatch.setattr(alerts, "_fetch", fetch)
        alerts.fetch_warnings([Place("all", ("FR718", "CH021", "FR101"))])
        assert len([url for url in calls if "/cap/" in url]) == 1


class TestTheWarningItself:
    @staticmethod
    def warning(onset, expires, severity="Moderate"):
        return WeatherWarning("e", severity, "a", onset, expires)

    def test_it_covers_its_own_day(self):
        warning = self.warning("2026-09-30T12:00:00+00:00", "2026-09-30T20:00:00+00:00")
        assert warning.covers("2026-09-30")

    def test_it_covers_every_day_it_spans(self):
        warning = self.warning("2026-09-30T22:00:00+00:00", "2026-10-02T06:00:00+00:00")
        assert warning.days == ["2026-09-30", "2026-10-01", "2026-10-02"]
        assert warning.covers("2026-10-01")

    def test_it_does_not_cover_the_day_before(self):
        warning = self.warning("2026-09-30T12:00:00+00:00", "2026-09-30T20:00:00+00:00")
        assert not warning.covers("2026-09-29")

    def test_an_unreadable_timestamp_covers_nothing(self):
        assert not self.warning("gestern", "morgen").covers("2026-09-30")
        assert self.warning("gestern", "morgen").days == []

    @pytest.mark.parametrize("severity, color", [
        ("Moderate", "#f6c744"), ("Severe", "#ef6c00"), ("Extreme", "#c62828"),
    ])
    def test_the_colour_follows_the_severity(self, severity, color):
        assert self.warning("", "", severity).color == color

    def test_an_unknown_severity_still_gets_a_colour(self):
        assert self.warning("", "", "Nonsense").color == alerts.DEFAULT_SEVERITY_COLOR

    def test_worse_warnings_rank_higher(self):
        assert self.warning("", "", "Extreme").rank > self.warning("", "", "Moderate").rank

    def test_it_survives_the_cache_round_trip(self):
        warning = WeatherWarning("Sturm", "Severe", "Bern", "a", "b", "l", "h", "d", "i", "s")
        assert WeatherWarning.from_dict(warning.to_dict()) == warning
