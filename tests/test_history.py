"""Tests for the night counter and the location history.

The counter spans a whole evening: lowered at night, raised in the morning, with a
reboot and any number of interrupted moves possibly in between. Those are the cases
worth pinning.
"""

import json

import pytest

from bedliftcontrol import history as history_module
from bedliftcontrol.history import MAX_LOCATIONS, History, LocationVisit


@pytest.fixture
def history(tmp_path):
    return History(path=str(tmp_path / "history.json"))


def lower(tracker):
    tracker.record_bed_position(at_top=False, at_bottom=True)


def raise_bed(tracker):
    return tracker.record_bed_position(at_top=True, at_bottom=False)


def stop_halfway(tracker):
    return tracker.record_bed_position(at_top=False, at_bottom=False)


class TestNightCounter:
    def test_starts_at_zero(self, history):
        assert history.nights == 0

    def test_a_full_night_counts_once(self, history):
        lower(history)
        assert raise_bed(history) is True
        assert history.nights == 1

    def test_raising_without_having_been_down_does_not_count(self, history):
        """The bed starts parked at the top; raising it again is not a night."""
        assert raise_bed(history) is False
        assert history.nights == 0

    def test_lowering_alone_does_not_count(self, history):
        lower(history)
        assert history.nights == 0

    def test_lowering_twice_does_not_count_twice(self, history):
        lower(history)
        lower(history)
        raise_bed(history)
        assert history.nights == 1

    def test_raising_twice_counts_once(self, history):
        lower(history)
        raise_bed(history)
        assert raise_bed(history) is False
        assert history.nights == 1

    def test_several_nights_add_up(self, history):
        for _ in range(5):
            lower(history)
            raise_bed(history)
        assert history.nights == 5

    def test_a_stop_halfway_counts_nothing(self, history):
        assert stop_halfway(history) is False
        assert history.nights == 0

    def test_stops_on_the_way_up_do_not_break_the_night(self, history):
        """Lowered in the evening, then raised in two goes with a stop in between."""
        lower(history)
        stop_halfway(history)
        assert raise_bed(history) is True
        assert history.nights == 1

    def test_stops_on_the_way_down_do_not_count_early(self, history):
        stop_halfway(history)
        lower(history)
        stop_halfway(history)
        assert raise_bed(history) is True
        assert history.nights == 1


class TestNightCounterPersistence:
    def test_the_count_survives_a_restart(self, tmp_path):
        path = str(tmp_path / "history.json")
        first = History(path=path)
        lower(first)
        raise_bed(first)
        assert History(path=path).nights == 1

    def test_a_night_spanning_a_restart_still_counts(self, tmp_path):
        """Lowered in the evening, Pi rebooted, raised in the morning."""
        path = str(tmp_path / "history.json")
        evening = History(path=path)
        lower(evening)
        morning = History(path=path)
        assert raise_bed(morning) is True
        assert morning.nights == 1

    def test_a_restart_after_raising_does_not_recount(self, tmp_path):
        path = str(tmp_path / "history.json")
        first = History(path=path)
        lower(first)
        raise_bed(first)
        second = History(path=path)
        assert raise_bed(second) is False
        assert second.nights == 1


class TestLocationHistory:
    def test_starts_empty(self, history):
        assert history.locations == []
        assert history.last_location is None

    def test_the_first_position_is_recorded(self, history):
        assert history.record_position(46.72, 7.56, "Thun") is True
        assert len(history.locations) == 1
        assert history.locations[0].city == "Thun"

    def test_the_same_position_is_not_recorded_again(self, history):
        history.record_position(46.72, 7.56, "Thun")
        assert history.record_position(46.72, 7.56, "Thun") is False
        assert len(history.locations) == 1

    def test_a_new_position_is_appended(self, history):
        history.record_position(46.72, 7.56, "Thun")
        assert history.record_position(47.37, 8.55, "Zurich") is True
        assert [entry.city for entry in history.locations] == ["Thun", "Zurich"]

    def test_returning_to_a_previous_place_is_recorded(self, history):
        """Only the immediately preceding position counts as unchanged."""
        history.record_position(46.72, 7.56, "Thun")
        history.record_position(47.37, 8.55, "Zurich")
        assert history.record_position(46.72, 7.56, "Thun") is True
        assert len(history.locations) == 3

    def test_float_jitter_is_not_a_new_position(self, history):
        history.record_position(46.72, 7.56, "Thun")
        assert history.record_position(46.720000001, 7.560000001, "Thun") is False

    def test_a_move_beyond_the_precision_is_recorded(self, history):
        history.record_position(46.7200, 7.5600, "Thun")
        assert history.record_position(46.7300, 7.5600, "Thun") is True

    def test_every_entry_carries_a_timestamp(self, history, monkeypatch):
        from datetime import datetime

        monkeypatch.setattr(history_module.clock, "now", lambda: datetime(2026, 9, 14, 17, 4, 12))
        history.record_position(46.72, 7.56, "Thun")
        assert history.locations[0].at == "2026-09-14T17:04:12"

    def test_the_list_is_capped(self, history):
        for index in range(MAX_LOCATIONS + 20):
            history.record_position(46.0 + index / 1000, 7.0, f"Ort {index}")
        assert len(history.locations) == MAX_LOCATIONS

    def test_capping_drops_the_oldest(self, history):
        for index in range(MAX_LOCATIONS + 5):
            history.record_position(46.0 + index / 1000, 7.0, f"Ort {index}")
        assert history.locations[0].city == "Ort 5"
        assert history.locations[-1].city == f"Ort {MAX_LOCATIONS + 4}"

    def test_locations_survive_a_restart(self, tmp_path):
        path = str(tmp_path / "history.json")
        first = History(path=path)
        first.record_position(46.72, 7.56, "Thun")
        first.record_position(47.37, 8.55, "Zurich")
        assert [entry.city for entry in History(path=path).locations] == ["Thun", "Zurich"]

    def test_the_same_position_after_a_restart_is_not_recorded_again(self, tmp_path):
        path = str(tmp_path / "history.json")
        first = History(path=path)
        first.record_position(46.72, 7.56, "Thun")
        assert History(path=path).record_position(46.72, 7.56, "Thun") is False


class TestStorage:
    def test_a_missing_file_is_fine(self, tmp_path):
        tracker = History(path=str(tmp_path / "nothing.json"))
        assert tracker.nights == 0
        assert tracker.locations == []

    def test_a_corrupt_file_does_not_raise(self, tmp_path):
        path = tmp_path / "history.json"
        path.write_text("{not json")
        tracker = History(path=str(path))
        assert tracker.nights == 0

    def test_a_file_with_a_broken_entry_does_not_raise(self, tmp_path):
        path = tmp_path / "history.json"
        path.write_text(json.dumps({"nights": 3, "locations": [{"city": "Thun"}]}))
        tracker = History(path=str(path))
        assert tracker.nights == 3

    def test_nothing_is_written_before_there_is_something_to_write(self, tmp_path):
        path = tmp_path / "history.json"
        History(path=str(path))
        assert not path.exists()

    def test_a_failing_write_does_not_propagate(self, tmp_path, monkeypatch):
        """record_bed_position runs inside the movement thread."""
        tracker = History(path=str(tmp_path / "history.json"))

        def boom(*_args, **_kwargs):
            raise OSError("read only filesystem")

        monkeypatch.setattr(history_module.os, "replace", boom)
        lower(tracker)
        assert raise_bed(tracker) is True
        assert tracker.nights == 1, "the in memory count must still be right"

    def test_the_file_is_json_we_can_read_back(self, tmp_path):
        path = tmp_path / "history.json"
        tracker = History(path=str(path))
        lower(tracker)
        raise_bed(tracker)
        tracker.record_position(46.72, 7.56, "Thun")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["nights"] == 1
        assert data["locations"][0]["city"] == "Thun"


class TestLocationVisit:
    def test_round_trips_through_json(self):
        visit = LocationVisit("2026-09-14T17:04:12", "Thun", 46.72, 7.56)
        assert LocationVisit.from_dict(visit.to_dict()) == visit

    def test_position_is_rounded_for_comparison(self):
        visit = LocationVisit("2026-09-14T17:04:12", "Thun", 46.7200001, 7.5599999)
        assert visit.position == (46.72, 7.56)


class TestJumpRecord:
    def test_nothing_played_is_zero(self, tmp_path):
        assert History(path=str(tmp_path / "history.json")).best_jump_score == 0

    def test_the_first_score_is_a_record(self, tmp_path):
        tracker = History(path=str(tmp_path / "history.json"))
        assert tracker.record_jump_result(12) is True
        assert tracker.best_jump_score == 12

    def test_a_higher_score_replaces_it(self, tmp_path):
        tracker = History(path=str(tmp_path / "history.json"))
        tracker.record_jump_result(12)
        assert tracker.record_jump_result(30) is True
        assert tracker.best_jump_score == 30

    def test_a_lower_score_is_kept_out(self, tmp_path):
        tracker = History(path=str(tmp_path / "history.json"))
        tracker.record_jump_result(30)
        assert tracker.record_jump_result(12) is False
        assert tracker.best_jump_score == 30

    def test_the_same_score_again_is_no_record(self, tmp_path):
        tracker = History(path=str(tmp_path / "history.json"))
        tracker.record_jump_result(30)
        assert tracker.record_jump_result(30) is False

    def test_it_survives_a_restart(self, tmp_path):
        path = str(tmp_path / "history.json")
        History(path=path).record_jump_result(30)
        assert History(path=path).best_jump_score == 30

    def test_an_older_file_without_it_still_loads(self, tmp_path):
        path = tmp_path / "history.json"
        path.write_text(json.dumps({"nights": 3}), encoding="utf-8")
        tracker = History(path=str(path))
        assert tracker.best_jump_score == 0 and tracker.nights == 3
