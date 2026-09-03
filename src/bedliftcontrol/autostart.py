"""Install/remove a desktop autostart entry so the app starts with the Pi desktop.

This is a one-time setup helper, not something main.py runs on every launch.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DESKTOP_FILENAME = "bedliftcontrol.desktop"


def default_autostart_dir() -> Path:
    return Path.home() / ".config" / "autostart"


def default_exec_command() -> str:
    # Use the current interpreter so it also works from inside a virtual environment.
    return f"{sys.executable} -m bedliftcontrol.main"


def build_desktop_entry(exec_command: str) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=BedLiftControl\n"
        "Comment=Controlling bed motors and relays\n"
        f"Exec={exec_command}\n"
        "Terminal=false\n"
    )


def install(autostart_dir: Path | None = None, exec_command: str | None = None) -> Path:
    autostart_dir = autostart_dir or default_autostart_dir()
    exec_command = exec_command or default_exec_command()
    autostart_dir.mkdir(parents=True, exist_ok=True)
    target = autostart_dir / DESKTOP_FILENAME
    target.write_text(build_desktop_entry(exec_command))
    return target


def uninstall(autostart_dir: Path | None = None) -> bool:
    autostart_dir = autostart_dir or default_autostart_dir()
    target = autostart_dir / DESKTOP_FILENAME
    if target.exists():
        target.unlink()
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install or remove the BedLiftControl desktop autostart entry."
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove the autostart entry instead of installing it.",
    )
    args = parser.parse_args()

    if args.uninstall:
        removed = uninstall()
        print("Autostart entry removed." if removed else "No autostart entry found.")
    else:
        target = install()
        print(f"Autostart entry installed at {target}")
        print("BedLiftControl will start on the next desktop login.")


if __name__ == "__main__":
    main()
