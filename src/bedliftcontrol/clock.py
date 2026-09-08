"""Date and time for the main panel.

Deliberately separate from the weather blocks: the weather refresh skips everything
while there is no reading (no internet, failed fetch, first seconds after start), and
the clock has to keep running exactly then. It also ticks far more often than the
weather is refreshed.

The German weekday and month names are spelled out here instead of coming from
strftime, whose output depends on the process locale - which differs between the
Windows development machine and the Raspberry Pi.
"""

from datetime import datetime

WEEKDAYS = (
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
)
MONTHS = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)


def format_date(moment: datetime) -> str:
    """Long form, e.g. 'Dienstag, 8. September 2026'."""
    return f"{WEEKDAYS[moment.weekday()]}, {moment.day}. {MONTHS[moment.month - 1]} {moment.year}"


def format_time(moment: datetime) -> str:
    """24 hour clock with seconds, e.g. '08:05:09'."""
    return f"{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}"


def now() -> datetime:
    """Wrapped so tests and callers have a single place to patch."""
    return datetime.now()
