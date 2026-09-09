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
│   ├── config.json          # Persistent settings (steps, speed, position, kiosk)
│   └── weather.json         # Weather cache, written at runtime
├── deploy/
│   └── bedliftcontrol.desktop   # Reference autostart entry
├── src/
│   └── bedliftcontrol/
│       ├── __init__.py
│       ├── autostart.py     # Installs/removes the desktop autostart entry
│       ├── clock.py         # Date and time formatting (German, locale independent)
│       ├── config.py        # Config dataclass, load/save JSON
│       ├── controller.py    # BedController: motion + GPIO logic (no GUI)
│       ├── gui.py           # BedGui: CustomTkinter user interface
│       ├── icons.py         # Canvas-drawn weather icons
│       ├── main.py          # Entry point
│       ├── timesync.py      # Keeps the shown clock right when the Pi's is not
│       └── weather.py       # Location, forecast and the WMO code table
├── tests/
├── DEPLOYMENT.md
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

| Signal     | GPIO (BCM) |
|------------|------------|
| FRONT_PUL  | 27         |
| FRONT_DIR  | 22         |
| BACK_PUL   | 24         |
| BACK_DIR   | 23         |

## Configuration

All settings live in a single file, `data/config.json`:

| Key              | Meaning                                                  |
|------------------|----------------------------------------------------------|
| `total_steps`    | Steps for a full up/down travel                          |
| `speed_pps`      | Motor speed in pulses per second                         |
| `position_steps` | Where the bed stands: `0` fully down, `total_steps` fully up |
| `bed_up`         | Derived from `position_steps`, not maintained by hand     |
| `kiosk`          | Fullscreen instead of a window                           |

The file is written automatically when settings change, when the bed is moved and
when a movement is stopped.

`position_steps` is the single source of truth for the bed position. Editing
`bed_up` by hand has no effect — it is overwritten from `position_steps` on the
next save.

## Weather

When the Pi has internet (e.g. phone tethering while camping), the main panel shows
the current weather. Location is derived from the public IP (rough, city level) and
the forecast comes from [Open-Meteo](https://open-meteo.com) — both free and without
an API key. The last result is cached to `data/weather.json`, so the weather stays
visible when the connection drops. No configuration is required.

Location and forecast are refreshed every 30 minutes; the display re-reads the
cached values every 5 seconds. The icons are drawn on a canvas rather than taken
from emoji, because Unicode has no graded weather glyphs (there is exactly one
"cloud with rain") and Tk renders emoji monochrome with gaps that differ between
Windows and the Pi.

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

## Kiosk mode

⚙ → "Kiosk-Modus einschalten" switches from the fixed window to fullscreen, which
is the sensible mode on the Pi's 800×480 panel. The setting is persisted, so the
Pi comes up in fullscreen. There is no title bar in that mode; the way back is the
same button, or `Esc` with a keyboard attached.
