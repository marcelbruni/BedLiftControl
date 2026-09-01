from time import sleep
from enum import Enum
from pathlib import Path
from guizero import App, Box, Text, TextBox, PushButton, info, Slider, Window
import RPi.GPIO as GPIO

# state files live in the repo's data/ directory
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
STEPS_FILE = str(DATA_DIR / "steps.txt")
SPEED_FILE = str(DATA_DIR / "speed.txt")
POSITION_FILE = str(DATA_DIR / "position.txt")

# enums
class Direction(Enum):
    UP = 0
    DOWN = 1

class Pins(Enum):
    FRONT_PUL = 27
    BACK_PUL = 24
    FRONT_DIR = 22
    BACK_DIR = 23

# methods for reading files
def read_steps_file():
    with open(STEPS_FILE) as f:
        lines = f.readlines()
    totalsteps = int(lines[0])
    print("steps: " + str(totalsteps))
    return totalsteps

def read_speed_file():
    with open(SPEED_FILE) as f:
        lines = f.readlines()
    speed = float(lines[0])
    print("speed: " + str(speed))
    return speed

def read_position_file():
    position = False
    fileName = POSITION_FILE
    print("Reading " + fileName)
    with open(fileName) as f:
        lines = f.readlines()
    if(lines[0] == "1"):
        position = True
        set_slider_value(100)
    print("isBedUp: " + str(position))
    return int(lines[0])

# methods for writing files
def write_steps_file(steps):
    f = open(STEPS_FILE, 'w')
    f.write(str(steps))
    f.close()
    steps_text.value = "total steps: " + str(steps)

def write_speed_file(pps):
    f = open(SPEED_FILE, 'w')
    f.write(str(pps))
    f.close()
    speed_text.value = "speed in pps: " + str(pps)

def write_position_file(position):
    f = open(POSITION_FILE, 'w')
    f.write(str(position))
    f.close()
    if(position == "1"):
        set_slider_value(100)
        position_text.value = "bed up: True"
    else:
        set_slider_value(0)
        position_text.value = "bed up: False"

# methods setting gui elements
def set_slider_value(value):
    slider.enabled = True
    slider.value = value
    slider.enabled = False

# methods for calculations
def calculate_sleep_from_pps(pps):
    return (1 / pps) / 2

# methods for additional windows
def settings_window():
    window = Window(app, layout="grid", width="575", height="213", bg="dim grey", title="Settings")
    Text(window, grid=[0,0], align="right", text="total steps", font="Piboto")
    Text(window, grid=[0,1], align="right", text="bed up", font="Piboto")
    Text(window, grid=[0,2], align="right", text="speed pps", font="Piboto")
    steps_slider = Slider(window, grid=[1,0], align="left", height="40", width="488", start=27000, end=30000, command=write_steps_file)
    steps_slider.value = read_steps_file()
    steps_slider.text_size = 12
    position_slider = Slider(window, grid=[1,1], align="left", height="40", width="488", start=0, end=1, command=write_position_file)
    position_slider.value = read_position_file()
    position_slider.text_size = 12
    speed_slider = Slider(window, grid=[1,2], align="left", height="40", width="488", start=200, end=1400, command=write_speed_file)
    speed_slider.value = read_speed_file()
    speed_slider.text_size = 12

def corrections_window():
    text_size = 28
    button_width= 10
    button_height=3
    window = Window(app, layout="grid", width="590", height="350", bg="dim grey", title="Corrections")
    Text(window, grid=[0,0], text="  ")
    Text(window, grid=[1,0], text="back correction")
    Text(window, grid=[2,0], text="     ")
    Text(window, grid=[3,0], text="front correction")
    Text(window, grid=[0,1], text="  ")
    back_up_button = PushButton(window, grid=[1,1], width=button_width, height=button_height, command=correct_back_up, text="↑")
    back_up_button.text_size = text_size
    Text(window, grid=[2,1], text="     ")
    front_up_button = PushButton(window, grid=[3,1], width=button_width, height=button_height, command=correct_front_up, text="↑")
    front_up_button.text_size = text_size
    Text(window, grid=[0,2], text="  ")
    back_down_button = PushButton(window, grid=[1,2], width=button_width, height=button_height, command=correct_back_down, text="↓")
    back_down_button.text_size = text_size
    Text(window, grid=[2,2], text="     ")
    front_down_button = PushButton(window, grid=[3,2], width=button_width, height=button_height, command=correct_front_down, text="↓")
    front_down_button.text_size = text_size

def not_implemented_window():
    window = Window(app, width="200", height="40", bg="dim grey", title="Not Implemented!")
    Text(window, text="not implemented!")

# methods for setting up stuff
def gpio_setup():
    GPIO.setmode(GPIO.BCM)                      # choose BCM for GPIO numbering
    GPIO.setup(Pins.FRONT_PUL.value, GPIO.OUT)  # set FRONT_PUL as PUL 
    GPIO.setup(Pins.FRONT_DIR.value, GPIO.OUT)  # set FRONT_DIR as DIR
    GPIO.setup(Pins.BACK_PUL.value, GPIO.OUT)   # set BACK_PUL as PUL 
    GPIO.setup(Pins.BACK_DIR.value, GPIO.OUT)   # set BACK_DIR as DIR

# methods for pulse pin step looping
def move_steps(direction, steps):
    print("movesteps 1")
    change_direction(direction)
    print("movesteps 2")
    sleeptime = calculate_sleep_from_pps(read_speed_file())
    print("movesteps 3")
    print(sleeptime)
    for x in range(steps):
        move_step(sleeptime)
    print('move finished')

def move_steps_single_back(direction, steps):
    change_direction(direction)
    sleeptime = calculate_sleep_from_pps(read_speed_file())
    for x in range(steps):
        move_step_single_back(sleeptime)
    print('move finished')

def move_steps_single_front(direction, steps):
    change_direction(direction)
    sleeptime = calculate_sleep_from_pps(read_speed_file())
    for x in range(steps):
        move_step_single_front(sleeptime)
    print('move finished')

# methods for single step pulse pin output
def move_step(sleeptime):
    GPIO.output(Pins.FRONT_PUL.value, 1)     # set FRONT_PUL to 1/GPIO.HIGH/True
    GPIO.output(Pins.BACK_PUL.value, 1)     # set BACK_PUL to 1/GPIO.HIGH/True
    sleep(sleeptime)
    GPIO.output(Pins.FRONT_PUL.value, 0)     # set FRONT_PUL to 0/GPIO.LOW/False
    GPIO.output(Pins.BACK_PUL.value, 0)     # set BACK_PUL to 0/GPIO.LOW/False
    sleep(sleeptime)

def move_step_single_back(sleeptime):
    GPIO.output(Pins.BACK_PUL.value, 1)     # set BACK_PUL to 1/GPIO.HIGH/True
    sleep(sleeptime)
    GPIO.output(Pins.BACK_PUL.value, 0)     # set BACK_PUL to 0/GPIO.LOW/False
    sleep(sleeptime)

def move_step_single_front(sleeptime):
    GPIO.output(Pins.FRONT_PUL.value, 1)     # set BACK_PUL to 1/GPIO.HIGH/True
    sleep(sleeptime)
    GPIO.output(Pins.FRONT_PUL.value, 0)     # set BACK_PUL to 0/GPIO.LOW/False
    sleep(sleeptime)

# methods for direction pin outputs
def change_direction(newDirection):
    if newDirection > 0:
        GPIO.output(Pins.FRONT_DIR.value, Direction.DOWN.value)
        GPIO.output(Pins.BACK_DIR.value, Direction.DOWN.value)
    else:
        GPIO.output(Pins.FRONT_DIR.value, Direction.UP.value)
        GPIO.output(Pins.BACK_DIR.value, Direction.UP.value)

# methods for motor movements
def correct_back_up():
    move_steps_single_back(Direction.UP.value, 100)

def correct_back_down():
    move_steps_single_back(Direction.DOWN.value, 100)

def correct_front_up():
    move_steps_single_front(Direction.UP.value, 100)

def correct_front_down():
    move_steps_single_front(Direction.DOWN.value, 100)

def move_up():
    print("test 1")
    up_button.enabled = False
    down_button.enabled = True
    print("test 2")
    move_steps(Direction.UP.value, read_steps_file())
    print("test 3")
    write_position_file(1)
    print("test 4")
    set_slider_value(100)
    position_text.value = "bed up: " + str(bool(read_position_file()))
    info("Bett oben", "Sicherungsseile anbringen und Motoren ausschalten!")

def move_down():
    up_button.enabled = True
    down_button.enabled = False
    info("Bett herunterfahren", "Motoren einschalten und Sicherungsseile lösen!")
    move_steps(Direction.DOWN.value, read_steps_file())
    write_position_file(0)
    set_slider_value(0)
    position_text.value = "bed up: " + str(bool(read_position_file()))

# ---------------------------------------------
# initializing main window
app = App(title="Steuerung Bettmotoren", width=800, height=420, bg="dim grey")
app.font = "Piboto Bold"
app.text_color = "white"

# setting up GPIO
gpio_setup()

# setting up up/down control box and buttons
updown_box = Box(app, height="fill", align="right", border=True)
updown_box.text_color = "white"
up_button = PushButton(updown_box, align="top", width=1, height=1, command=move_up, text="↑")
up_button.text_size = 118
down_button = PushButton(updown_box, align="bottom", width=1, height=1, command=move_down, text="↓")
down_button.text_size = 118

# setting up main box (slider box + content box)
main_box = Box(app, layout="grid", align="top", width="fill", height="370", border=True)
main_box.bg = "dim grey"
main_box.text_color = "white"

# setting up slider box (left element)
slider_box = Box(main_box, grid=[0,0], align="left", width="40", height="370", border=False, enabled=False)
slider_box.bg = "dim grey"
slider_box.text_color = "white"
slider = Slider(slider_box, horizontal=False, align="left", height='370', width="40", start=100, end=0)
slider.text_size=12
if(read_position_file()):
    up_button.enabled = False
else:
    down_button.enabled = False

# setting up content box (center element)
content_box = Box(main_box, grid=[1,0], layout="grid", align="top", width="fill", height="370", border=False)
state_title = Text(content_box, grid=[0,0], align="left", text="States")
position_text = Text(content_box, grid=[0,1], align="left", text="bed up: " + str(bool(read_position_file())), font="Piboto")
twothirty_text = Text(content_box, grid=[0,2], align="left", text="230V running: not implemented yet", font="Piboto")
motors_text = Text(content_box, grid=[0,3], align="left", text="24V running: not implemented yet", font="Piboto")
config_title = Text(content_box, grid=[0,4], align="left", text="Settings")
steps_text = Text(content_box, grid=[0,5], align="left", text="total steps: " + str(read_steps_file()), font="Piboto")
speed_text = Text(content_box, grid=[0,6], align="left", text="speed in pps: " + str(read_speed_file()), font="Piboto")

# setting up button box (bottom element)
button_box = Box(app, width="fill", height=50, align="bottom", border=True)
button_box.bg = "dim grey"
button_box.text_color = "white"
PushButton(button_box, align="left", width=2, command=settings_window, text="⚙")
PushButton(button_box, align="left", width=2, command=corrections_window, text="↑↓")
PushButton(button_box, align="left", width=10, command=not_implemented_window, text="230V on/off")

# render app
app.display()