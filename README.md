# BedLiftControl

Raspberry Pi controller for two stepper motors that raise and lower a bed in a car.

The application shows a [guizero](https://lawsie.github.io/guizero/) GUI to move the
bed up and down, adjust speed and total steps, and apply manual front/back
corrections. Motor pulses are sent over the Raspberry Pi GPIO pins via `RPi.GPIO`.

## Project structure

```
BedLiftControl/
├── data/                       # Runtime state files (steps, speed, position)
│   ├── steps.txt
│   ├── speed.txt
│   └── position.txt
├── src/
│   └── bedliftcontrol/
│       ├── __init__.py
│       └── bedcontrolv2.py     # Main application
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
python src/bedliftcontrol/bedcontrolv2.py
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

## Notes

The current code is a first version and will be cleaned up. Paths to the state
files are currently hard-coded to `/home/pi/Desktop/`.
