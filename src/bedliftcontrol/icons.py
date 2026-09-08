"""Canvas-drawn weather icons.

Emoji cannot express intensity: Unicode has exactly one "cloud with rain" and one
"cloud with snow" glyph, none with a varying number of drops or flakes, and none that
combines rain with ice or a thunderstorm with hail. On top of that Tk renders emoji
monochrome and falls back to a tofu box wherever the installed font has no outline,
which differs between Windows (Segoe UI Emoji) and the Raspberry Pi (Noto Color Emoji).

So the icons are drawn instead. Every icon is composed from parts placed in a 0..1 unit
square and scaled to the requested pixel size, which lets one definition serve the 52px
panel icon, the 34px forecast icon and the 26px reference table alike.
"""

import math
import tkinter
from dataclasses import dataclass

CLOUD_COLOR = "#b8c4d0"
SUN_COLOR = "#f5c542"
RAIN_COLOR = "#5aa0e0"
SNOW_COLOR = "#ffffff"
ICE_COLOR = "#8fe3f0"
BOLT_COLOR = "#f5c542"
HAIL_COLOR = "#dff3ff"
FOG_COLOR = "#9aa6b2"
UNKNOWN_COLOR = "#888888"


@dataclass(frozen=True)
class IconSpec:
    """What an icon is made of. The counts drive the intensity ladders."""

    sun: bool = False
    cloud: bool = True
    small_cloud: bool = False  # mainly-clear: sun dominates, cloud only peeks in
    fog_lines: int = 0
    drops: int = 0      # rain: slanted strokes
    dots: int = 0       # drizzle: small dots
    flakes: int = 0     # snow: six-spoke stars
    hail: int = 0       # hail: small circles
    grains: int = 0     # snow grains: many tiny dots, lighter than flakes
    bolt: bool = False
    ice: bool = False
    mark_shift: float = 0.0  # nudge the precipitation marks aside from the ice marker


# One icon per weather code. Intensity is simply the number of drops/dots/flakes/grains.
ICON_SPECS = {
    "sun": IconSpec(sun=True, cloud=False),
    "sun-cloud-light": IconSpec(sun=True, small_cloud=True),
    "sun-cloud": IconSpec(sun=True),
    "cloud": IconSpec(),
    "fog": IconSpec(fog_lines=3),
    "fog-ice": IconSpec(fog_lines=3, ice=True),
    "drizzle-1": IconSpec(dots=1),
    "drizzle-2": IconSpec(dots=2),
    "drizzle-3": IconSpec(dots=3),
    "drizzle-ice-1": IconSpec(dots=1, ice=True),
    "drizzle-ice-2": IconSpec(dots=2, ice=True, mark_shift=-0.10),
    "rain-1": IconSpec(drops=1),
    "rain-2": IconSpec(drops=2),
    "rain-3": IconSpec(drops=3),
    "rain-ice-3": IconSpec(drops=3, ice=True),
    "rain-ice-4": IconSpec(drops=4, ice=True),
    "snow-1": IconSpec(flakes=1),
    "snow-2": IconSpec(flakes=2),
    "snow-3": IconSpec(flakes=3),
    "grains": IconSpec(grains=5),
    "shower-1": IconSpec(sun=True, drops=1),
    "shower-2": IconSpec(sun=True, drops=2),
    "shower-3": IconSpec(sun=True, drops=3),
    "snow-shower-1": IconSpec(sun=True, flakes=1),
    "snow-shower-2": IconSpec(sun=True, flakes=2),
    "thunder": IconSpec(bolt=True),
    "thunder-hail-2": IconSpec(bolt=True, hail=2),
    "thunder-hail-4": IconSpec(bolt=True, hail=4),
    "unknown": IconSpec(cloud=False),
}

# The sun peeks out top-left when a cloud sits in front of it, and fills the square alone.
_SUN_WITH_CLOUD = (0.34, 0.30, 0.17)  # cx, cy, r
_SUN_ALONE = (0.50, 0.50, 0.24)
_CLOUD_BOX = (0.18, 0.30, 0.92, 0.66)  # x0, y0, x1, y1 - shifted right to free the sun
_CLOUD_BOX_SMALL = (0.40, 0.42, 0.94, 0.68)
_CLOUD_BOX_NO_SUN = (0.10, 0.28, 0.90, 0.66)
_PRECIP_Y = 0.74
_PRECIP_SPAN = (0.22, 0.80)
_PRECIP_GAP = 0.29  # cap, so two marks sit as tight as three instead of at the edges
_ICE_CENTER = (0.84, 0.84, 0.13)


def _oval(canvas, size, cx, cy, r, color):
    canvas.create_oval((cx - r) * size, (cy - r) * size, (cx + r) * size, (cy + r) * size,
                       fill=color, outline="")


def _line(canvas, size, x0, y0, x1, y1, color, width):
    canvas.create_line(x0 * size, y0 * size, x1 * size, y1 * size,
                       fill=color, width=max(1, round(width * size)), capstyle="round")


def _spoked(canvas, size, cx, cy, radius, color, width):
    """Three crossing lines - a six-spoke star, used for snowflakes and the ice marker."""
    for index in range(3):
        angle = index * math.pi / 3
        dx, dy = math.cos(angle), math.sin(angle)
        _line(canvas, size, cx - dx * radius, cy - dy * radius,
              cx + dx * radius, cy + dy * radius, color, width)


def _sun(canvas, size, cx, cy, r):
    _oval(canvas, size, cx, cy, r * 0.62, SUN_COLOR)
    for index in range(8):
        angle = index * math.pi / 4
        dx, dy = math.cos(angle), math.sin(angle)
        _line(canvas, size, cx + dx * r * 0.80, cy + dy * r * 0.80,
              cx + dx * r * 1.28, cy + dy * r * 1.28, SUN_COLOR, 0.035)


def _cloud(canvas, size, box):
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    _oval(canvas, size, x0 + width * 0.28, y0 + height * 0.58, height * 0.42, CLOUD_COLOR)
    _oval(canvas, size, x0 + width * 0.52, y0 + height * 0.42, height * 0.52, CLOUD_COLOR)
    _oval(canvas, size, x0 + width * 0.78, y0 + height * 0.62, height * 0.38, CLOUD_COLOR)
    canvas.create_rectangle(x0 * size, (y1 - height * 0.40) * size, x1 * size, y1 * size,
                            fill=CLOUD_COLOR, outline="")


def _spread(count, gap=_PRECIP_GAP):
    """Centred x positions for `count` precipitation marks.

    The marks keep a fixed gap and are centred as a group, rather than being stretched
    across the whole span - two marks pushed to the left and right edge read as a gap in
    the icon instead of as "moderate". The gap still shrinks once the marks would not
    fit, so three and four marks are laid out exactly as before.
    """
    low, high = _PRECIP_SPAN
    center = (low + high) / 2
    if count <= 1:
        return [center]
    gap = min(gap, (high - low) / (count - 1))
    start = center - gap * (count - 1) / 2
    return [start + gap * index for index in range(count)]


def _drops(canvas, size, count, shift=0.0):
    for x in _spread(count):
        _line(canvas, size, x + shift + 0.03, _PRECIP_Y, x + shift - 0.03,
              _PRECIP_Y + 0.19, RAIN_COLOR, 0.055)


def _dots(canvas, size, count, shift=0.0):
    for x in _spread(count):
        _oval(canvas, size, x + shift, _PRECIP_Y + 0.09, 0.043, RAIN_COLOR)


def _flakes(canvas, size, count, shift=0.0):
    for x in _spread(count):
        _spoked(canvas, size, x + shift, _PRECIP_Y + 0.09, 0.085, SNOW_COLOR, 0.038)


def _grains(canvas, size, count):
    """Snow grains: many tiny dots, staggered. Reads as granular and stays visually
    lighter than the flakes of an actual snowfall icon."""
    for index, x in enumerate(_spread(count, gap=1.0)):
        y = _PRECIP_Y + (0.04 if index % 2 == 0 else 0.16)
        _oval(canvas, size, x, y, 0.034, SNOW_COLOR)


def _hail(canvas, size, count):
    # staggered in two rows, so "more hail" reads without the icon getting wider, and
    # spread over the full span so the grains stay clear of the bolt in the middle
    for index, x in enumerate(_spread(count, gap=1.0)):
        y = _PRECIP_Y + (0.02 if index % 2 == 0 else 0.16)
        _oval(canvas, size, x, y, 0.048, HAIL_COLOR)


def _bolt(canvas, size):
    points = [(0.50, 0.62), (0.36, 0.84), (0.47, 0.84), (0.40, 1.00),
              (0.62, 0.78), (0.51, 0.78), (0.58, 0.62)]
    canvas.create_polygon([coord * size for point in points for coord in point],
                          fill=BOLT_COLOR, outline="")


def _fog(canvas, size, count):
    for index in range(count):
        y = _PRECIP_Y - 0.06 + index * 0.12
        inset = 0.08 if index % 2 else 0.0
        _line(canvas, size, 0.12 + inset, y, 0.88 - inset, y, FOG_COLOR, 0.055)


def _ice(canvas, size):
    _spoked(canvas, size, *_ICE_CENTER, ICE_COLOR, 0.05)


def _unknown(canvas, size):
    canvas.create_rectangle(0.2 * size, 0.2 * size, 0.8 * size, 0.8 * size,
                            outline=UNKNOWN_COLOR, width=max(1, round(0.04 * size)))
    canvas.create_text(0.5 * size, 0.5 * size, text="?", fill=UNKNOWN_COLOR,
                       font=("Roboto", max(6, round(size * 0.4))))


def draw_icon(canvas, key, size) -> None:
    """Draw `key` onto `canvas`, clearing whatever was drawn before."""
    canvas.delete("all")
    spec = ICON_SPECS.get(key)
    if spec is None or key == "unknown":
        _unknown(canvas, size)
        return
    if spec.sun:
        _sun(canvas, size, *(_SUN_WITH_CLOUD if spec.cloud else _SUN_ALONE))
    if spec.cloud:
        if spec.small_cloud:
            box = _CLOUD_BOX_SMALL
        else:
            box = _CLOUD_BOX if spec.sun else _CLOUD_BOX_NO_SUN
        _cloud(canvas, size, box)
    if spec.fog_lines:
        _fog(canvas, size, spec.fog_lines)
    if spec.drops:
        _drops(canvas, size, spec.drops, spec.mark_shift)
    if spec.dots:
        _dots(canvas, size, spec.dots, spec.mark_shift)
    if spec.flakes:
        _flakes(canvas, size, spec.flakes, spec.mark_shift)
    if spec.grains:
        _grains(canvas, size, spec.grains)
    if spec.hail:
        _hail(canvas, size, spec.hail)
    if spec.bolt:
        _bolt(canvas, size)
    if spec.ice:
        _ice(canvas, size)


class IconCanvas(tkinter.Canvas):
    """Fixed-size canvas that renders one weather icon and can swap it out."""

    def __init__(self, master, size: int, background: str):
        super().__init__(master, width=size, height=size, bg=background,
                         highlightthickness=0, borderwidth=0)
        self._size = size
        self._key = None

    def show(self, key: str) -> None:
        if key == self._key:
            return
        self._key = key
        draw_icon(self, key, self._size)
