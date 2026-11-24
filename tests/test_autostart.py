from __future__ import annotations

import shlex
import sys

import pytest

from specter import autostart

linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


@pytest.fixture(autouse=True)
def fake_config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


def exec_args(text: str) -> list[str]:
    line = next(l for l in text.splitlines() if l.startswith("Exec="))
    return shlex.split(line[len("Exec="):])


# --- Linux ---------------------------------------------------------------------------------

@linux_only
def test_entry_path_follows_xdg_config_home(tmp_path):
    assert autostart.entry_path() == tmp_path / "autostart" / "specter.desktop"


@linux_only
def test_enable_and_disable():
    assert not autostart.is_enabled()
    assert autostart.set_enabled(True)
    assert autostart.is_enabled()
    text = autostart.entry_path().read_text()
    assert text.startswith("[Desktop Entry]\n") and "Type=Application" in text
    assert exec_args(text) == [sys.executable, "-m", "specter"]
    assert autostart.set_enabled(False)
    assert not autostart.is_enabled()
    assert autostart.set_enabled(False)  # already off is fine


@linux_only
def test_exec_line_quotes_awkward_paths():
    cmd = ["/home/me/my apps/python", '-m', 'spe"cter', "50%"]
    assert exec_args(autostart.desktop_entry(cmd).replace("%%", "%")) == [
        "/home/me/my apps/python", "-m", 'spe"cter', "50%"
    ]
    assert "50%%" in autostart.desktop_entry(cmd)  # a literal % is written %%


@linux_only
def test_frozen_build_starts_its_own_binary(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert autostart.command() == [sys.executable]


@linux_only
def test_unwritable_folder_reports_failure(fake_config_home):
    (fake_config_home / "autostart").write_text("a file where the folder should be")
    assert autostart.set_enabled(True) is False


# --- Windows -------------------------------------------------------------------------------

@pytest.fixture
def fake_registry(monkeypatch):
    """Replace the Run key helpers with a dict, so tests never touch the real registry."""
    store = {}

    def get(name):
        return store.get(name)

    def set_(name, value):
        store[name] = value

    def delete(name):
        store.pop(name, None)

    monkeypatch.setattr(autostart, "_reg_get", get)
    monkeypatch.setattr(autostart, "_reg_set", set_)
    monkeypatch.setattr(autostart, "_reg_delete", delete)
    return store


@windows_only
def test_windows_is_supported():
    assert autostart.supported()


@windows_only
def test_windows_enable_writes_pythonw_command(fake_registry, tmp_path, monkeypatch):
    python = tmp_path / "python.exe"
    pythonw = tmp_path / "pythonw.exe"
    python.write_text("")
    pythonw.write_text("")
    monkeypatch.setattr(sys, "executable", str(python))
    assert not autostart.is_enabled()
    assert autostart.set_enabled(True)
    assert autostart.is_enabled()
    assert fake_registry["Specter"] == autostart.run_value([str(pythonw), "-m", "specter"])
    assert fake_registry["Specter"].endswith("pythonw.exe -m specter")


@windows_only
def test_windows_falls_back_to_python_without_pythonw(tmp_path, monkeypatch):
    python = tmp_path / "python.exe"
    python.write_text("")
    monkeypatch.setattr(sys, "executable", str(python))
    assert autostart.windows_command() == [str(python), "-m", "specter"]


@windows_only
def test_windows_frozen_build_starts_its_own_exe(fake_registry, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\Specter.exe")
    assert autostart.set_enabled(True)
    assert fake_registry["Specter"] == r"C:\Apps\Specter.exe"


@windows_only
def test_windows_path_with_spaces_is_quoted():
    value = autostart.run_value([r"C:\Program Files\Python38\pythonw.exe", "-m", "specter"])
    assert value == r'"C:\Program Files\Python38\pythonw.exe" -m specter'


@windows_only
def test_windows_disable_removes_value(fake_registry):
    assert autostart.set_enabled(True)
    assert autostart.set_enabled(False)
    assert "Specter" not in fake_registry
    assert not autostart.is_enabled()
    assert autostart.set_enabled(False)  # already off is fine


@windows_only
def test_windows_registry_errors_report_failure(monkeypatch):
    def boom(*args):
        raise PermissionError("access denied")

    monkeypatch.setattr(autostart, "_reg_get", boom)
    monkeypatch.setattr(autostart, "_reg_set", boom)
    monkeypatch.setattr(autostart, "_reg_delete", boom)
    assert autostart.set_enabled(True) is False
    assert autostart.set_enabled(False) is False
    assert autostart.is_enabled() is False


@windows_only
def test_windows_real_registry_round_trip(monkeypatch):
    """One live round trip under a test-only value name; always cleaned up."""
    monkeypatch.setattr(autostart, "VALUE_NAME", "SpecterTest")
    try:
        assert autostart.set_enabled(True)
        assert autostart.is_enabled()
        assert autostart._reg_get("SpecterTest") == autostart.run_value()
        assert autostart.set_enabled(False)
        assert not autostart.is_enabled()
    finally:
        autostart._reg_delete("SpecterTest")
    assert autostart._reg_get("SpecterTest") is None
