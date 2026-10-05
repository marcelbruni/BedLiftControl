"""Tests for the log file.

The point of the file is that a failure on the road can be read afterwards, so these
tests check that things really arrive in it - including the crashes that never go
through logging on their own.
"""

import logging
import sys
import threading

import pytest

from bedliftcontrol import logsetup


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    """Configures logging into a throwaway file and puts everything back afterwards."""
    root = logging.getLogger()
    previous_handlers, previous_level = root.handlers[:], root.level
    previous_hooks = (sys.excepthook, threading.excepthook)
    path = tmp_path / "bedliftcontrol.log"
    logsetup.configure(str(path))
    yield path
    for handler in root.handlers:
        handler.close()
    root.handlers, root.level = previous_handlers, previous_level
    sys.excepthook, threading.excepthook = previous_hooks


def read(path) -> str:
    for handler in logging.getLogger().handlers:
        handler.flush()
    return path.read_text(encoding="utf-8")


class TestTheFile:
    def test_a_message_lands_in_it(self, log_file):
        logging.getLogger("bedliftcontrol.test").info("Bett oben")
        assert "Bett oben" in read(log_file)

    def test_it_says_when_and_how_bad(self, log_file):
        logging.getLogger("bedliftcontrol.test").warning("Seile")
        line = read(log_file).strip()
        assert "WARNING" in line and "bedliftcontrol.test" in line
        assert line[:4].isdigit(), "the line has to start with a date"

    def test_the_console_still_gets_it_too(self, log_file):
        """Started from a terminal, the output must not disappear into the file."""
        streams = [h for h in logging.getLogger().handlers
                   if type(h) is logging.StreamHandler]
        assert streams

    def test_a_directory_that_cannot_be_written_is_survivable(self, tmp_path):
        """A full or read-only SD card must not stop the bed from working."""
        logsetup.configure(str(tmp_path / "no" / "such" / "place.log"))
        logging.getLogger("bedliftcontrol.test").info("trotzdem da")  # must not raise
        assert not any(isinstance(h, logging.handlers.RotatingFileHandler)
                       for h in logging.getLogger().handlers)

    def test_it_rotates_instead_of_growing_forever(self, log_file):
        handlers = [h for h in logging.getLogger().handlers
                    if isinstance(h, logging.handlers.RotatingFileHandler)]
        assert handlers, "no rotating handler installed"
        assert handlers[0].maxBytes == logsetup.MAX_BYTES
        assert handlers[0].backupCount == logsetup.BACKUP_COUNT

    def test_the_whole_log_is_capped(self):
        """Four megabytes at most on an SD card that also holds the system."""
        assert logsetup.MAX_BYTES * (logsetup.BACKUP_COUNT + 1) <= 4_000_000

    def test_it_lives_next_to_the_other_runtime_files(self):
        from pathlib import Path

        place = Path(logsetup.LOG_FILE)
        assert place.name == "bedliftcontrol.log" and place.parent.name == "data"


class TestCrashes:
    """None of these reach the file on their own - the interpreter prints them."""

    def test_an_unhandled_exception_is_written_down(self, log_file):
        try:
            raise ValueError("Motor weg")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        written = read(log_file)
        assert "CRITICAL" in written and "Motor weg" in written
        assert "Traceback" in written

    def test_a_crashing_thread_is_written_down(self, log_file):
        def boom():
            raise RuntimeError("Fahrt abgebrochen")

        thread = threading.Thread(target=boom, name="mover")
        thread.start()
        thread.join()
        written = read(log_file)
        assert "Fahrt abgebrochen" in written and "mover" in written

    def test_a_thread_ending_by_system_exit_is_not_a_crash(self, log_file):
        class Args:
            exc_type = SystemExit
            exc_value = SystemExit()
            exc_traceback = None
            thread = None

        logsetup._log_thread_exception(Args())
        assert "CRITICAL" not in read(log_file)

    def test_a_tk_callback_exception_is_written_down(self, log_file):
        """Every timer tick and button press of the app runs inside one of these."""
        try:
            raise KeyError("after-callback")
        except KeyError:
            logsetup.log_callback_exception(*sys.exc_info())
        assert "after-callback" in read(log_file)

    def test_it_takes_what_tk_actually_passes(self, log_file):
        """Tk looks the attribute up on the instance, so it hands over three arguments
        and no widget. A four-argument hook fails silently and the crash is lost."""
        import inspect

        parameters = inspect.signature(logsetup.log_callback_exception).parameters
        assert len(parameters) == 3


class TestReadingItBack:
    """What the panel shows."""

    def test_it_returns_the_last_lines(self, log_file):
        for number in range(10):
            logging.getLogger("bedliftcontrol.test").info("Zeile %s", number)
        tail = logsetup.read_tail(str(log_file), lines=3)
        assert len(tail.splitlines()) == 3
        assert "Zeile 9" in tail and "Zeile 6" not in tail

    def test_the_order_is_kept(self, log_file):
        """A traceback is several lines and is unreadable rearranged."""
        for number in range(4):
            logging.getLogger("bedliftcontrol.test").info("Zeile %s", number)
        lines = logsetup.read_tail(str(log_file)).splitlines()
        assert lines == sorted(lines, key=lambda line: int(line.rsplit(" ", 1)[1]))

    def test_a_short_log_comes_back_whole(self, log_file):
        logging.getLogger("bedliftcontrol.test").info("alles")
        assert "alles" in logsetup.read_tail(str(log_file), lines=400)

    def test_a_missing_file_is_not_an_error(self, tmp_path):
        assert logsetup.read_tail(str(tmp_path / "never_written.log")) == ""

    def test_a_broken_byte_does_not_stop_it(self, tmp_path):
        """The file is written while the power can drop; half a character is possible."""
        path = tmp_path / "broken.log"
        path.write_bytes("gut\n".encode("utf-8") + b"\xff\xfe kaputt\n")
        assert "gut" in logsetup.read_tail(str(path))
