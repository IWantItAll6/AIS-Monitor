import sys

from services import crash_handler


def test_install_logs_uncaught_exception_and_shows_dialog(tmp_path, monkeypatch, qapp):

    log_path = tmp_path / "crash.log"

    shown = []
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.critical",
        lambda *args, **kwargs: shown.append(args)
    )

    original_hook = sys.excepthook

    try:
        crash_handler.install(log_path=log_path)

        try:
            raise ValueError("synthetic test failure")

        except ValueError:
            sys.excepthook(*sys.exc_info())

        assert log_path.exists()
        assert "synthetic test failure" in log_path.read_text(encoding="utf-8")
        assert len(shown) == 1

    finally:
        sys.excepthook = original_hook


def test_install_does_not_show_dialog_for_keyboard_interrupt(tmp_path, monkeypatch, qapp):

    log_path = tmp_path / "crash.log"

    shown = []
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.critical",
        lambda *args, **kwargs: shown.append(args)
    )

    original_hook = sys.excepthook

    try:
        crash_handler.install(log_path=log_path)

        try:
            raise KeyboardInterrupt()

        except KeyboardInterrupt:
            sys.excepthook(*sys.exc_info())

        assert not log_path.exists()
        assert shown == []

    finally:
        sys.excepthook = original_hook
