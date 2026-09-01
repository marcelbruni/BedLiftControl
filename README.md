# BedLiftControl

Raspberry Pi controller for two stepper motors that raise and lower a bed in a car.

The application shows a [guizero](https://lawsie.github.io/guizero/) GUI to move the
bed up and down, adjust speed and total steps, and apply manual front/back
corrections. Motor pulses are sent over the Raspberry Pi GPIO pins via `RPi.GPIO`.

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
│       ├── gui.py           # BedGui: guizero user interface
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

## Tests

Characterization tests pin the current behaviour so a refactor can be verified to
not change anything. They mock `guizero` and `RPi.GPIO`, so they run on any
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
