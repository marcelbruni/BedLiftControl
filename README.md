# BedLiftControl

Raspberry Pi controller for two stepper motors that raise and lower a bed in a car.

The application shows a [CustomTkinter](https://customtkinter.tomschimansky.com/)
GUI to move the bed up and down, adjust speed and total steps, and apply manual
front/back corrections. Motor pulses are sent over the Raspberry Pi GPIO pins via
`RPi.GPIO`.

The code is split into layers: `config` (persistent settings), `controller`
(motion/hardware logic, no GUI) and `gui` (the CustomTkinter interface). This
keeps the logic testable without a Raspberry Pi.

Bed movement runs in a background thread, so the UI stays responsive while the
bed moves. Only one movement runs at a time. A movement can be interrupted with
the STOP button: the bed decelerates, the reached position is stored, and the
next movement either finishes the remaining travel or reverses back to where it
started.

## Project structure

```
BedLiftControl/
├── data/
│   ├── config.json          # Persistent settings (steps, speed, position, kiosk, location)
│   ├── history.json         # Night counter and location history, written at runtime
│   └── weather.json         # Weather cache, written at runtime
├── deploy/
│   └── bedliftcontrol.desktop   # Reference autostart entry
├── src/
│   └── bedliftcontrol/
│       ├── __init__.py
│       ├── alerts.py        # Official weather warnings from the MeteoAlarm feeds
│       ├── autostart.py     # Installs/removes the desktop autostart entry
│       ├── clock.py         # Date and time formatting (German, locale independent)
│       ├── config.py        # Config dataclass, load/save JSON
│       ├── controller.py    # BedController: motion + GPIO logic (no GUI)
│       ├── gui.py           # BedGui: CustomTkinter user interface
│       ├── history.py       # Night counter and location history
│       ├── icons.py         # Canvas-drawn weather icons
│       ├── inverter.py      # 230V inverter, switched over its remote contact
│       ├── main.py          # Entry point
│       ├── connectivity.py  # Is there a line yet? A TCP connect, nothing more
│       ├── logsetup.py      # Rotating log file plus the hooks that catch crashes
│       ├── timesync.py      # Keeps the shown clock right when the Pi's is not
│       ├── update.py        # Looks on GitHub and installs with git
│       └── weather.py       # Location, forecast and the WMO code table
├── tests/
├── DEPLOYMENT.md
├── WIRING.md
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

## Setup

> Für die Installation auf dem Raspberry Pi (inkl. Autostart und Updates)
> gibt es eine ausführliche Schritt-für-Schritt-Anleitung in
> [DEPLOYMENT.md](DEPLOYMENT.md).

```bash
python -m venv .venv
source .venv/bin/activate      # on the Raspberry Pi
pip install -r requirements.txt
```

> `RPi.GPIO` only installs on a Raspberry Pi.

## Run

```bash
cd src
python -m bedliftcontrol.main
```

Or, after `pip install -e .`, simply run the `bedliftcontrol` command.

## Autostart on the Raspberry Pi

To launch BedLiftControl automatically when the Pi's desktop starts, install a
`.desktop` entry into the user's autostart folder. Run this once on the Pi
(after `pip install -e .`):

```bash
bedliftcontrol-autostart            # install
bedliftcontrol-autostart --uninstall   # remove
```

This writes `~/.config/autostart/bedliftcontrol.desktop` pointing at the current
Python interpreter, so it also works from inside a virtual environment.

A reference entry is checked in at [deploy/bedliftcontrol.desktop](deploy/bedliftcontrol.desktop)
for manual installation. The equivalent manual steps:

1. `mkdir -p ~/.config/autostart`
2. `nano ~/.config/autostart/bedliftcontrol.desktop`
3. paste the contents of `deploy/bedliftcontrol.desktop` (adjust `Exec` to your setup)

If the GPIO pins need root access, add your user to the `gpio` group
(`sudo adduser $USER gpio`) rather than running the app with `sudo` — using
`sudo` in the autostart entry would bypass your virtual environment.

## Tests

Characterization tests pin the current behaviour so a refactor can be verified to
not change anything. They mock `customtkinter` and `RPi.GPIO`, so they run on any
machine (no Raspberry Pi required).

On the Raspberry Pi (or any machine with Python on the PATH):

```bash
pip install -r requirements-dev.txt
pytest
```

On a Windows dev machine using a local virtual environment:

```powershell
# one-time setup
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# run the tests (repeat this any time)
.\.venv\Scripts\python.exe -m pytest
```

## Hardware

Two stepper motor drivers (front and back), each wired with a pulse (PUL) and
direction (DIR) pin:

| Signal          | GPIO (BCM) | Board pin |
|-----------------|------------|-----------|
| FRONT_PUL       | 27         | 13        |
| FRONT_DIR       | 22         | 15        |
| BACK_PUL        | 24         | 18        |
| BACK_DIR        | 23         | 16        |
| INVERTER_REMOTE | 17         | 11        |

The inverter pin drives a relay across the inverter's remote terminal, see below.
Step-by-step wiring instructions are in [WIRING.md](WIRING.md).

## Configuration

All settings live in a single file, `data/config.json`:

| Key              | Meaning                                                  |
|------------------|----------------------------------------------------------|
| `total_steps`    | Steps for a full up/down travel                          |
| `speed_pps`      | Motor speed in pulses per second                         |
| `position_steps` | Where the bed stands: `0` fully down, `total_steps` fully up |
| `bed_up`         | Derived from `position_steps`, not maintained by hand     |
| `kiosk`          | Fullscreen instead of a window                           |
| `weather_location` | Selected weather location, `phone` follows the public IP |
| `rope_delay_seconds` | Extra wait before the bed leaves the top, for the ropes (0-20) |

The file is written automatically when settings change, when the bed is moved and
when a movement is stopped.

`position_steps` is the single source of truth for the bed position. Editing
`bed_up` by hand has no effect — it is overwritten from `position_steps` on the
next save.

## 230V inverter

The motors run off a Victron inverter whose remote terminal is a potential-free contact:
closed means on. A relay on GPIO 17 sits across that contact, so the app can switch mains
power the same way a wall switch would.

The "230V" button in the bottom bar switches it by hand. Its label never changes; the
colour is the state, red while mains is live and grey while it is not. Starting a bed movement switches it on by itself and waits
before the motors turn — the inverter's output is not stable the instant the contact
closes. The wait is shown as a countdown on the STOP button, and STOP during the
countdown drops the movement while leaving the inverter running.

The correction panel does the same in miniature: mains comes on when it opens and off
when it is left, because those buttons drive the motors too.

A movement that reaches an end stop switches it off again: at the bottom silently, at the
top after the "Sicherungsseile anbringen!" prompt is acknowledged — the motors hold the
bed while the ropes go on. A movement stopped half way leaves it running, because the bed
is still hanging there and the rest of the travel needs the motors.

Lowering from the very top waits a second time, for the safety ropes: **Seile lösen**,
0 to 20 seconds, added on top of the start-up. The countdown says so - "230V startet"
while mains comes up, then "Seile lösen!" for the rest - and it only ever appears on the
way down from the top, where the ropes actually are.

The start-up wait is fixed at five seconds, measured in the vehicle; only **Seile lösen**
is a setting. There is no switch to turn the automatic off - without it a movement has no
power at all, which is not a mode worth offering.

Two deliberate choices:

- **The state is not persisted.** After a restart the relay is open and the inverter off.
  Restoring "on" at boot would switch mains power on in an unattended vehicle.
- **The button is dead while the bed moves.** Cutting power mid travel would drop the
  motors and leave `position_steps` pointing at a place the bed no longer is.

Closing the app releases the GPIO pins, which opens the relay and switches the inverter
off as well.

## Weather

When the Pi has internet (e.g. phone tethering while camping), the main panel shows
the weather from [Open-Meteo](https://open-meteo.com) — free and without an API key.
No configuration is required.

Next to the city sits the two-letter weekday of the reading on display - taken from the
reading's own timestamp, so an hours-old one does not claim to be today.

The **Ort** dropdown in the settings picks the location: the current one, derived from the public IP
(rough, city level), or one of the places we travel to — Höfen bei Thun, Châtel,
La Cure, Schilthorn, Crans-Montana. Every refresh fetches **all** of them in a single
request and caches the lot to `data/weather.json`, so switching is instant and the
last readings stay visible when the connection drops.

A refresh runs once an hour. While offline nothing is fetched at all: instead a plain
TCP connect to the weather host every 15 seconds asks whether there is a line yet, and
the real request follows the moment there is - so the weather appears within seconds of
the hotspot coming up, without a failing request every minute in between. The display
re-reads the cached values every 5 seconds, and that is also what carries it over
midnight - no fetch involved:

- Days that are in the past drop out of the week row, so today is always the first
  column. Offline the row simply gets shorter as the days run out.
- A reading from a previous day is no longer "now", so the big block switches to today's
  entry from the week instead, showing that day's high and low in place of the
  measured temperature. The "Stand" line says "Vorhersage" while it does.
- With neither a fresh reading nor a forecast for today, the last measurement stays on
  screen with its own date - better than an empty panel.

The IP lookup (ipapi.co) answers HTTP 429 after a few calls in quick succession. A
failed lookup therefore keeps the last known position instead of dropping the phone
location — a parked vehicle has not moved anyway.

The icons are drawn on a canvas rather than taken from emoji, because Unicode has no
graded weather glyphs (there is exactly one "cloud with rain") and Tk renders emoji
monochrome with gaps that differ between Windows and the Pi.

## Weather warnings

What MeteoSchweiz and Meteo-France issue, taken from the open MeteoAlarm Atom feeds.
A warning marks the weather icon of the day it is in force on - today's on the big icon,
a later one on that day's column - and tapping the marked icon opens the full text.
Yellow, orange and red follow MeteoAlarm's own severities.

The feeds shape what is possible here:

- **No geometry.** Neither the feed entry nor the linked CAP document carries a polygon,
  only a NUTS3 code and an area name. A warning can therefore only be matched to a place
  whose region is written down in `LOCATIONS` - which is why **the phone position gets no
  warnings**: it moves, and there is nothing to match it against.
- The codes are NUTS **2013**, confirmed against the live feed (FR712 Ardeche, FR713
  Drome, FR715 Loire in the official order). Area names are matched as well, because the
  Swiss feed was empty while this was built and its identifiers could not be verified -
  an unmatched area is logged, which is how the missing ones will surface.
- The text is fetched while the connection is there, not when the warning is opened, so a
  warning read in the morning still opens in the evening. At most twelve detail requests
  per refresh, one per document however many places share it.

The MeteoAlarm EDR API would answer by coordinate and would solve the phone position, but
its data queries need a membership (HTTP 401); only the feeds are open.

## Views

Everything the bar opens takes over the centre area instead of opening a window: the
weather makes way for the settings or the corrections, and a back button appears in the
top right corner. From the settings, "Historie" and "Wetter-Icons" go one level deeper
and their back button returns to the settings. Pressing ⚙ or ↑↓ again while that panel
is up goes straight back to the weather.

The weather is only unpacked, never destroyed, so the five-second refresh keeps writing
into it behind the panel and it returns exactly as it was. The panels are the other way
round: built when entered, destroyed when left, so the history and the version line are
never stale. Both deep panels scroll, because neither fits the 800x480 panel.

The settings and the corrections are deliberately no wider than the weather they replace.
Wider, and the centre area would grow and squeeze the arrow buttons every time a panel
opened.

Nothing opens a window any more. The "Sicherungsseile anbringen!" prompt at the top end
stop and the weather warning behind a marked icon are panels like the rest; the prompt
takes over from whatever was showing, because it matters more, and a movement started
from it returns to the weather. Leaving the prompt is the acknowledgement that cuts
mains. No system dialog is left anywhere - the update button writes its own answer.

## Tracking

⚙ → "Historie" shows two long lived numbers, kept in `data/history.json`:

- **Übernachtungen** — one per night. Counted when the bed comes back up from having
  been all the way down, so lowering in the evening and raising in the morning is
  exactly one. Interrupted moves and reboots in between do not disturb it, and raising
  a bed that was never lowered counts nothing.
- **Standort-Historie** — the phone position with a timestamp, appended whenever it
  differs from the one before it. Capped at the newest 1000 entries.

The file is separate from `config.json` on purpose: that one is tracked by git and the
update procedure resets it, which would wipe the counter. `history.json` is gitignored
and survives updates.

## Clock

The panel shows the date and time, corrected against an internet reference.

A Raspberry Pi has no battery backed real time clock, so without a network it
starts up with whatever time it last saw. The offset between the machine clock and
the HTTP `Date` header of the weather API is measured hourly and applied to the
display, which keeps ticking at full accuracy while offline. Where the sudo right
from [DEPLOYMENT.md](DEPLOYMENT.md) is in place, the system clock is corrected as
well, once it is off by two seconds or more.

NTP does the same job better whenever it works — this is the fallback for the time
before the first NTP sync and for networks that block UDP 123, which phone
tethering and public WiFi often do.

## Updates

The settings carry the version that is running - the checked-out commit and its date -
and an **Install updates** button next to it. Nothing is checked in the background:
looking and installing are one action, started by that button.

It asks GitHub whether the checkout is behind its remote branch (`git fetch` plus
`git rev-list --count HEAD..@{u}`). The answer goes on the button itself - "Bereits
aktuell" or "Fehlgeschlagen" - and the button stays dead afterwards: there is nothing
more to get, or something is wrong that pressing again will not mend. Leaving the
settings rebuilds the panel, which is how to try again; why it failed is in the log,
`data/bedliftcontrol.log`.
If there is something to install, it
discards the checked-in `data/config.json`, fast-forwards, writes the live config back
and restarts the process with `os.execv`. Writing the config back is what keeps the bed
position, the location and the delays across an update - without it, the pull would
reset them to the committed values.

The button is refused while the bed is moving, and only the two git steps are run: the
app is an editable install, so a pull is enough for code changes. A release that changes
the dependencies still needs the terminal, see [DEPLOYMENT.md](DEPLOYMENT.md#update).

## Logging

Everything goes to `data/bedliftcontrol.log` as well as to the console, rotating at 1 MB
with three older files kept - 4 MB at most on an SD card that also holds the system. The
console half only helps on a development machine: the Pi starts the app from a desktop
autostart entry with `Terminal=false`, so without the file a failure on the road leaves
nothing to look at.

Crashes do not go through logging on their own, so three hooks put them in the file too:
`sys.excepthook`, `threading.excepthook`, and Tk's `report_callback_exception` - the last
one matters most, because every timer tick and every button press of this app runs inside
a Tk callback.

⚙ → "Log" shows the last 400 lines on the panel itself, scrolled to the end, so a failure
on the road can be read without a terminal. Whole lines in their original order: a
traceback is several of them and is unreadable rearranged or cut in the middle.

## Touch panel

Two things the 7" panel needs that a desktop does not:

- **No hover.** A touch screen sends no leave event, so a tapped button keeps its hover
  colour until something else is touched - it looks as if the wrong state were latched.
  Every button and the dropdown are built with `hover=False`.
- **No flicker.** The countdown ticks four times a second; the STOP button is only
  reconfigured when its text actually changes, and both of its fonts are built once
  instead of per tick.
- **A stub that does not grow with the window.** The bit of green left when the bed is
  up carries the bed icon, and is counted in pixels rather than as a fraction of the
  bar: as a fraction it grew with the window and left the fill's rounded corners showing
  above the icon on the taller kiosk screen.
- **Finger sized targets.** The bottom bar is 55px tall and every button in it is the
  same 90x45, taken from the widest label. The clock sits at the right in two lines,
  time over date, sized to stay inside those 55px - anything taller pushes the bar open
  and shifts the whole layout.

## Kiosk mode

⚙ → "Kiosk-Modus einschalten" switches from the fixed window to fullscreen, which
is the sensible mode on the Pi's 800×480 panel. The setting is persisted, so the
Pi comes up in fullscreen. There is no title bar in that mode; the way back is the
same button, or `Esc` with a keyboard attached.
