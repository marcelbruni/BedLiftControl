"""Jump: hop over what comes at you, a little faster every second.

Pure logic in world units (1 unit = 1 pixel on the canvas), no Tk, so the physics can
be tested without a window. The GUI ticks it and draws the result.

Obstacle gaps are measured in seconds of travel, not in pixels: the jump arc lasts the
same time at any speed, so a time based gap stays clearable to the very end. What gets
harder is the warning: the run from the right edge to the player shrinks from 2.5s to
well under a second.
"""

import random
from dataclasses import dataclass, field

WORLD_WIDTH = 440.0
PLAYER_X = 60.0
PLAYER_SIZE = 26.0

GRAVITY = 1400.0
JUMP_VELOCITY = 470.0  # peaks at 79 units, so every obstacle can be cleared

START_SPEED = 150.0
MAX_SPEED = 480.0
ACCELERATION = 6.0

MIN_GAP_SECONDS = 1.1  # longer than the 0.67s in the air, so there is ground to land on
MAX_GAP_SECONDS = 2.1
OBSTACLE_WIDTH = (14.0, 24.0)
OBSTACLE_HEIGHT = (22.0, 40.0)

SCORE_UNIT = 20.0
RESTART_LOCK_SECONDS = 0.8  # long enough to read the score before a stray tap restarts
MAX_FRAME_SECONDS = 0.05  # a stalled frame must not teleport the player through a cactus

READY = "ready"
RUNNING = "running"
OVER = "over"


@dataclass
class Obstacle:
    x: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width


@dataclass
class JumpGame:
    """`rng` is injectable so a test can lay out obstacles it knows the size of."""

    rng: object = field(default_factory=random.Random)
    state: str = READY
    height: float = 0.0
    vertical_speed: float = 0.0
    speed: float = START_SPEED
    distance: float = 0.0
    obstacles: list = field(default_factory=list)
    gap_left: float = 0.0
    since_over: float = 0.0

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.state = READY
        self.height = 0.0
        self.vertical_speed = 0.0
        self.speed = START_SPEED
        self.distance = 0.0
        self.obstacles = []
        self.gap_left = self._new_gap()
        self.since_over = 0.0

    @property
    def airborne(self) -> bool:
        return self.height > 0.0

    @property
    def score(self) -> int:
        return int(self.distance / SCORE_UNIT)

    @property
    def can_restart(self) -> bool:
        return self.state == OVER and self.since_over >= RESTART_LOCK_SECONDS

    def jump(self) -> bool:
        """The single input. True when the tap did something."""
        if self.state == READY:
            self.state = RUNNING
            self.vertical_speed = JUMP_VELOCITY
            return True
        if self.state == RUNNING:
            if self.airborne:
                return False
            self.vertical_speed = JUMP_VELOCITY
            return True
        if self.can_restart:
            self.reset()
            return True
        return False

    def tick(self, elapsed: float) -> None:
        elapsed = min(elapsed, MAX_FRAME_SECONDS)
        if self.state == OVER:
            self.since_over += elapsed
            return
        if self.state != RUNNING:
            return
        self.speed = min(MAX_SPEED, self.speed + ACCELERATION * elapsed)
        moved = self.speed * elapsed
        self.distance += moved
        self._move_obstacles(moved)
        self._fall(elapsed)
        if self._collides():
            self.state = OVER
            self.since_over = 0.0

    def _fall(self, elapsed: float) -> None:
        if not self.airborne and self.vertical_speed <= 0.0:
            return
        self.vertical_speed -= GRAVITY * elapsed
        self.height += self.vertical_speed * elapsed
        if self.height <= 0.0:
            self.height = 0.0
            self.vertical_speed = 0.0

    def _move_obstacles(self, moved: float) -> None:
        for obstacle in self.obstacles:
            obstacle.x -= moved
        self.obstacles = [obstacle for obstacle in self.obstacles if obstacle.right > 0.0]
        self.gap_left -= moved
        if self.gap_left <= 0.0:
            self.obstacles.append(self._new_obstacle())
            self.gap_left = self._new_gap()

    def _new_obstacle(self) -> Obstacle:
        return Obstacle(
            x=WORLD_WIDTH,
            width=self.rng.uniform(*OBSTACLE_WIDTH),
            height=self.rng.uniform(*OBSTACLE_HEIGHT),
        )

    def _new_gap(self) -> float:
        return self.speed * self.rng.uniform(MIN_GAP_SECONDS, MAX_GAP_SECONDS)

    def _collides(self) -> bool:
        right = PLAYER_X + PLAYER_SIZE
        return any(
            obstacle.x < right and obstacle.right > PLAYER_X and self.height < obstacle.height
            for obstacle in self.obstacles
        )
