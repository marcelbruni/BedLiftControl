"""Tests for the drawn weather icons.

A recording fake stands in for the Tk canvas, so the drawing logic is tested without a
display and the intensity ladders (more drops / more flakes / more hail) are asserted as
counts rather than eyeballed.
"""

import pytest

from bedliftcontrol.icons import ICON_SPECS, draw_icon

SIZE = 40


class FakeCanvas:
    """Records what would be drawn instead of drawing it."""

    def __init__(self):
        self.ovals = []
        self.lines = []
        self.polygons = []
        self.rectangles = []
        self.texts = []
        self.cleared = 0

    def delete(self, _tag):
        self.cleared += 1

    def create_oval(self, *coords, **kwargs):
        self.ovals.append((coords, kwargs))

    def create_line(self, *coords, **kwargs):
        self.lines.append((coords, kwargs))

    def create_polygon(self, coords, **kwargs):
        self.polygons.append((coords, kwargs))

    def create_rectangle(self, *coords, **kwargs):
        self.rectangles.append((coords, kwargs))

    def create_text(self, *coords, **kwargs):
        self.texts.append((coords, kwargs))

    def all_coords(self):
        flat = []
        for coords, _ in self.ovals + self.lines + self.rectangles + self.texts:
            flat.extend(coords)
        for coords, _ in self.polygons:
            flat.extend(coords)
        return flat

    def lines_colored(self, color):
        return [line for line in self.lines if line[1].get("fill") == color]

    def ovals_colored(self, color):
        return [oval for oval in self.ovals if oval[1].get("fill") == color]


def render(key):
    canvas = FakeCanvas()
    draw_icon(canvas, key, SIZE)
    return canvas


class TestDrawIcon:
    def test_clears_before_drawing(self):
        assert render("sun").cleared == 1

    @pytest.mark.parametrize("key", sorted(ICON_SPECS))
    def test_every_spec_draws_something(self, key):
        canvas = render(key)
        assert canvas.all_coords(), f"{key} drew nothing"

    @pytest.mark.parametrize("key", sorted(ICON_SPECS))
    def test_every_spec_stays_inside_the_square(self, key):
        """An icon drawing outside its canvas would be clipped, not just ugly."""
        coords = render(key).all_coords()
        assert min(coords) >= 0, f"{key} draws left of / above the canvas"
        assert max(coords) <= SIZE, f"{key} draws past the canvas edge"

    def test_unknown_key_draws_the_placeholder(self):
        canvas = render("no-such-icon")
        assert canvas.texts and canvas.texts[0][1]["text"] == "?"


class TestIntensityLadders:
    """The whole point of drawing instead of using emoji: gradable intensity."""

    @pytest.mark.parametrize(
        "lower, higher",
        [("rain-1", "rain-2"), ("rain-2", "rain-3"), ("rain-ice-3", "rain-ice-4"),
         ("shower-1", "shower-2"), ("shower-2", "shower-3")],
    )
    def test_more_rain(self, lower, higher):
        from bedliftcontrol.icons import RAIN_COLOR

        assert len(render(higher).lines_colored(RAIN_COLOR)) > len(render(lower).lines_colored(RAIN_COLOR))

    @pytest.mark.parametrize(
        "lower, higher",
        [("drizzle-1", "drizzle-2"), ("drizzle-2", "drizzle-3"), ("drizzle-ice-1", "drizzle-ice-2")],
    )
    def test_more_drizzle(self, lower, higher):
        from bedliftcontrol.icons import RAIN_COLOR

        assert len(render(higher).ovals_colored(RAIN_COLOR)) > len(render(lower).ovals_colored(RAIN_COLOR))

    @pytest.mark.parametrize(
        "lower, higher",
        [("snow-1", "snow-2"), ("snow-2", "snow-3"), ("snow-shower-1", "snow-shower-2")],
    )
    def test_more_snow(self, lower, higher):
        from bedliftcontrol.icons import SNOW_COLOR

        assert len(render(higher).lines_colored(SNOW_COLOR)) > len(render(lower).lines_colored(SNOW_COLOR))

    def test_more_hail(self):
        from bedliftcontrol.icons import HAIL_COLOR

        assert len(render("thunder-hail-4").ovals_colored(HAIL_COLOR)) > len(
            render("thunder-hail-2").ovals_colored(HAIL_COLOR)
        )

    def test_snow_grains_are_lighter_than_heavy_snowfall(self):
        from bedliftcontrol.icons import SNOW_COLOR

        assert len(render("flake").lines_colored(SNOW_COLOR)) < len(render("snow-3").lines_colored(SNOW_COLOR))


class TestIconParts:
    def test_freezing_icons_carry_the_ice_marker(self):
        from bedliftcontrol.icons import ICE_COLOR

        for key in ("fog-ice", "drizzle-ice-1", "drizzle-ice-2", "rain-ice-3", "rain-ice-4"):
            assert render(key).lines_colored(ICE_COLOR), f"{key} has no ice marker"

    def test_non_freezing_icons_have_no_ice_marker(self):
        from bedliftcontrol.icons import ICE_COLOR

        for key in ("fog", "drizzle-1", "rain-3", "snow-3", "thunder"):
            assert not render(key).lines_colored(ICE_COLOR), f"{key} should not show ice"

    def test_thunder_icons_carry_a_bolt(self):
        for key in ("thunder", "thunder-hail-2", "thunder-hail-4"):
            assert render(key).polygons, f"{key} has no bolt"

    def test_only_thunder_icons_carry_a_bolt(self):
        for key in ("rain-3", "snow-3", "shower-3", "fog"):
            assert not render(key).polygons, f"{key} should not show a bolt"

    def test_fog_draws_horizontal_lines(self):
        from bedliftcontrol.icons import FOG_COLOR

        lines = render("fog").lines_colored(FOG_COLOR)
        assert len(lines) == 3
        for (x0, y0, x1, y1), _ in lines:
            assert y0 == y1, "fog lines must be horizontal"
            assert x1 > x0
