"""guizero user interface for the bed lift. Delegates all motion to BedController."""

from guizero import App, Box, Text, PushButton, info, Slider, Window

from bedliftcontrol.controller import BedController

BACKGROUND_COLOR = "dim grey"
TEXT_COLOR = "white"
BED_UP_LABEL = "bed up: "
STEPS_LABEL = "total steps: "
SPEED_LABEL = "speed in pps: "


class BedGui:
    def __init__(self, controller: BedController):
        self.controller = controller
        self._build()

    def _build(self):
        self.app = App(title="Steuerung Bettmotoren", width=800, height=420, bg=BACKGROUND_COLOR)
        self.app.font = "Piboto Bold"
        self.app.text_color = TEXT_COLOR

        # up/down control buttons
        updown_box = Box(self.app, height="fill", align="right", border=True)
        updown_box.text_color = TEXT_COLOR
        self.up_button = PushButton(updown_box, align="top", width=1, height=1, command=self._on_up, text="↑")
        self.up_button.text_size = 118
        self.down_button = PushButton(updown_box, align="bottom", width=1, height=1, command=self._on_down, text="↓")
        self.down_button.text_size = 118

        # content box (states + settings display)
        main_box = Box(self.app, layout="grid", align="top", width="fill", height="370", border=True)
        main_box.bg = BACKGROUND_COLOR
        main_box.text_color = TEXT_COLOR
        content_box = Box(main_box, grid=[0, 0], layout="grid", align="top", width="fill", height="370", border=False)
        Text(content_box, grid=[0, 0], align="left", text="States")
        self.position_text = Text(content_box, grid=[0, 1], align="left", text=self._bed_up_text(), font="Piboto")
        Text(content_box, grid=[0, 2], align="left", text="230V running: not implemented yet", font="Piboto")
        Text(content_box, grid=[0, 3], align="left", text="24V running: not implemented yet", font="Piboto")
        Text(content_box, grid=[0, 4], align="left", text="Settings")
        self.steps_text = Text(content_box, grid=[0, 5], align="left", text=STEPS_LABEL + str(self.controller.config.total_steps), font="Piboto")
        self.speed_text = Text(content_box, grid=[0, 6], align="left", text=SPEED_LABEL + str(self.controller.config.speed_pps), font="Piboto")

        # bottom button bar
        button_box = Box(self.app, width="fill", height=50, align="bottom", border=True)
        button_box.bg = BACKGROUND_COLOR
        button_box.text_color = TEXT_COLOR
        PushButton(button_box, align="left", width=2, command=self._settings_window, text="⚙")
        PushButton(button_box, align="left", width=2, command=self._corrections_window, text="↑↓")
        PushButton(button_box, align="left", width=10, command=self._not_implemented_window, text="230V on/off")

        # initial enabled state reflects the stored position
        if self.controller.config.bed_up:
            self.up_button.enabled = False
        else:
            self.down_button.enabled = False

    def _bed_up_text(self):
        return BED_UP_LABEL + str(self.controller.config.bed_up)

    def _refresh_state(self):
        self.position_text.value = self._bed_up_text()

    def _on_up(self):
        self.up_button.enabled = False
        self.down_button.enabled = True
        self.controller.move_up()
        self._refresh_state()
        info("Bett oben", "Sicherungsseile anbringen und Motoren ausschalten!")

    def _on_down(self):
        self.up_button.enabled = True
        self.down_button.enabled = False
        info("Bett herunterfahren", "Motoren einschalten und Sicherungsseile lösen!")
        self.controller.move_down()
        self._refresh_state()

    def _settings_window(self):
        window = Window(self.app, layout="grid", width="575", height="150", bg=BACKGROUND_COLOR, title="Settings")
        Text(window, grid=[0, 0], align="right", text="total steps", font="Piboto")
        Text(window, grid=[0, 1], align="right", text="speed pps", font="Piboto")
        steps_slider = Slider(window, grid=[1, 0], align="left", height="40", width="488", start=27000, end=30000, command=self._on_steps_change)
        steps_slider.value = self.controller.config.total_steps
        steps_slider.text_size = 12
        speed_slider = Slider(window, grid=[1, 1], align="left", height="40", width="488", start=200, end=1400, command=self._on_speed_change)
        speed_slider.value = self.controller.config.speed_pps
        speed_slider.text_size = 12

    def _on_steps_change(self, value):
        self.controller.config.total_steps = int(value)
        self.controller.config.save()
        self.steps_text.value = STEPS_LABEL + str(int(value))

    def _on_speed_change(self, value):
        self.controller.config.speed_pps = float(value)
        self.controller.config.save()
        self.speed_text.value = SPEED_LABEL + str(value)

    def _corrections_window(self):
        text_size = 28
        button_width = 10
        button_height = 3
        window = Window(self.app, layout="grid", width="590", height="350", bg=BACKGROUND_COLOR, title="Corrections")
        Text(window, grid=[0, 0], text="  ")
        Text(window, grid=[1, 0], text="back correction")
        Text(window, grid=[2, 0], text="     ")
        Text(window, grid=[3, 0], text="front correction")
        Text(window, grid=[0, 1], text="  ")
        back_up_button = PushButton(window, grid=[1, 1], width=button_width, height=button_height, command=self.controller.correct_back_up, text="↑")
        back_up_button.text_size = text_size
        Text(window, grid=[2, 1], text="     ")
        front_up_button = PushButton(window, grid=[3, 1], width=button_width, height=button_height, command=self.controller.correct_front_up, text="↑")
        front_up_button.text_size = text_size
        Text(window, grid=[0, 2], text="  ")
        back_down_button = PushButton(window, grid=[1, 2], width=button_width, height=button_height, command=self.controller.correct_back_down, text="↓")
        back_down_button.text_size = text_size
        Text(window, grid=[2, 2], text="     ")
        front_down_button = PushButton(window, grid=[3, 2], width=button_width, height=button_height, command=self.controller.correct_front_down, text="↓")
        front_down_button.text_size = text_size

    def _not_implemented_window(self):
        window = Window(self.app, width="200", height="40", bg=BACKGROUND_COLOR, title="Not Implemented!")
        Text(window, text="not implemented!")

    def display(self):
        self.app.display()
