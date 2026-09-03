# BedLiftControl

Raspberry Pi controller for two stepper motors that raise and lower a bed in a car.

The application shows a [CustomTkinter](https://customtkinter.tomschimansky.com/)
GUI to move the bed up and down, adjust speed and total steps, and apply manual
front/back corrections. Motor pulses are sent over the Raspberry Pi GPIO pins via
`RPi.GPIO`.

The code is split into layers: `config` (persistent settings), `controller`
(motion/hardware logic, no GUI) and `gui` (guizero UI). This keeps the logic
testable without a Raspberry Pi.

Bed movement runs in a background thread, so the UI stays responsive while the
bed moves. Only one movement runs at a time.

## Project structure

```
BedLiftControl/
├── data/
│   └── config.json          # Persistent settings (steps, speed, bed position)
├── src/
│   └── bedliftcontrol/
│       ├── __init__.py
│       ├── config.py        # Config dataclass, load/save JSON
│       ├── controller.py    # BedController: motion + GPIO logic (no GUI)
│       ├── gui.py           # BedGui: CustomTkinter user interface
│       └── main.py          # Entry point
├── tests/
├── pyproject.toml
├── requirements.txt
└── README.md
```

## Setup

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

| Key           | Meaning                                  |
|---------------|------------------------------------------|
| `total_steps` | Steps for a full up/down travel          |
| `speed_pps`   | Motor speed in pulses per second         |
| `bed_up`      | Whether the bed is currently raised      |

The file is written automatically when settings change or the bed is moved.
