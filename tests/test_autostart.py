from __future__ import annotations

import shlex
import sys

import pytest

from specter import autostart

pytestmark = pytest.mark.skipif(not autostart.supported(), reason="Linux only")


@pytest.fixture(autouse=True)
def fake_config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


def exec_args(text: str) -> list[str]:
    line = next(l for l in text.splitlines() if l.startswith("Exec="))
    return shlex.split(line[len("Exec="):])


def test_entry_path_follows_xdg_config_home(tmp_path):
    assert autostart.entry_path() == tmp_path / "autostart" / "specter.desktop"


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


def test_exec_line_quotes_awkward_paths():
    cmd = ["/home/me/my apps/python", '-m', 'spe"cter', "50%"]
    assert exec_args(autostart.desktop_entry(cmd).replace("%%", "%")) == [
        "/home/me/my apps/python", "-m", 'spe"cter', "50%"
    ]
    assert "50%%" in autostart.desktop_entry(cmd)  # a literal % is written %%


def test_frozen_build_starts_its_own_binary(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert autostart.command() == [sys.executable]


def test_unwritable_folder_reports_failure(fake_config_home):
    (fake_config_home / "autostart").write_text("a file where the folder should be")
    assert autostart.set_enabled(True) is False
