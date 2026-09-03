"""Tests for the autostart desktop-entry installer."""

from bedliftcontrol import autostart


class TestBuildDesktopEntry:
    def test_contains_required_fields(self):
        entry = autostart.build_desktop_entry("python -m bedliftcontrol.main")
        assert "[Desktop Entry]" in entry
        assert "Type=Application" in entry
        assert "Exec=python -m bedliftcontrol.main" in entry
        assert "Terminal=false" in entry


class TestInstall:
    def test_writes_desktop_file(self, tmp_path):
        target = autostart.install(autostart_dir=tmp_path, exec_command="python -m bedliftcontrol.main")
        assert target == tmp_path / "bedliftcontrol.desktop"
        assert "Exec=python -m bedliftcontrol.main" in target.read_text()

    def test_creates_missing_directory(self, tmp_path):
        nested = tmp_path / "config" / "autostart"
        target = autostart.install(autostart_dir=nested, exec_command="x")
        assert target.exists()


class TestUninstall:
    def test_removes_existing_file(self, tmp_path):
        autostart.install(autostart_dir=tmp_path, exec_command="x")
        assert autostart.uninstall(autostart_dir=tmp_path) is True
        assert not (tmp_path / "bedliftcontrol.desktop").exists()

    def test_returns_false_when_nothing_to_remove(self, tmp_path):
        assert autostart.uninstall(autostart_dir=tmp_path) is False
