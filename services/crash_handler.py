import sys
import traceback
from datetime import datetime
from pathlib import Path

LOG_PATH = Path("data/crash.log")


def install(log_path=LOG_PATH):
    """Replaces the default uncaught-exception behavior (which otherwise
    just dumps a traceback to a console window most users never see, then
    the app silently disappears) with: log it to disk, and show a dialog
    so the user actually knows something went wrong."""

    def handle_exception(exc_type, exc_value, exc_tb):

        # Ctrl+C in a console should still behave like Ctrl+C, not pop a
        # crash dialog.
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)

            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n--- {datetime.now().isoformat()} ---\n{text}")

        except Exception:
            pass

        # Also to stderr — still useful when running from a terminal.
        sys.__excepthook__(exc_type, exc_value, exc_tb)

        try:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(
                None,
                "Unexpected Error",
                "AIS Monitor hit an unexpected error and may be unstable from "
                "here on — consider restarting it.\n\n"
                f"Details were saved to {log_path}.\n\n"
                f"{exc_type.__name__}: {exc_value}"
            )

        # A second failure while already handling a crash shouldn't itself
        # crash the handler — worst case, the user only gets the log file.
        except Exception:
            pass

    sys.excepthook = handle_exception
