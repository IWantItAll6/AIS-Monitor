import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():

    app = QApplication.instance() or QApplication([])

    yield app


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
