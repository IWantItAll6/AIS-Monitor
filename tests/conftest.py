import pytest
from PySide6.QtWidgets import QApplication

from services.settings_service import SettingsService


@pytest.fixture(scope="session")
def qapp():

    app = QApplication.instance() or QApplication([])

    yield app


@pytest.fixture(autouse=True)
def isolate_settings_file(tmp_path, monkeypatch):
    """Every MainWindow() construction calls SettingsService.load(), and
    some code paths call .save() — without this, either would read or
    write the real data/settings.json on disk, silently exposing the
    developer's actual saved settings to tests or overwriting them.
    Confirmed this really happens: a test exercising
    MainWindow.show_preferences() did exactly that once, flipping a real
    setting on a developer machine. Autouse, not opt-in, since almost
    every test in this suite constructs a MainWindow either directly or
    via another fixture."""

    monkeypatch.setattr(SettingsService, "SETTINGS_FILE", tmp_path / "settings.json")


def pytest_collection_modifyitems(items):
    """Tests marked @pytest.mark.serial measure real wall-clock time against
    a Qt event loop, and have been observed to fail intermittently only when
    run back-to-back after the rest of the (~90-test) suite — not on their
    own. Moving them to the very end at least keeps them out of whatever
    specific tests happen to precede them alphabetically; scripts/run_tests.py
    goes further and runs each in its own fresh process."""

    serial, rest = [], []

    for item in items:
        (serial if item.get_closest_marker("serial") else rest).append(item)

    items[:] = rest + serial
