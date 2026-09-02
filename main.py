import sys
import os
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from ui.main_window import MainWindow
from services import crash_handler


def main():

    # Every relative path in the app (data/, assets/, resources/) assumes
    # cwd is the project root. That's true when run from source, but a
    # PyInstaller onedir build's cwd is wherever the user launched it from
    # (e.g. their Desktop), not the folder the exe and its bundled data
    # actually live in — so anchor cwd there ourselves when frozen.
    if getattr(sys, "frozen", False):
        os.chdir(Path(sys.executable).parent)

    crash_handler.install()

    if sys.platform == "win32":
        # Without an explicit AppUserModelID, Windows groups the taskbar
        # entry under python.exe/pythonw.exe and shows ITS icon instead of
        # ours, no matter what QIcon is set on the window — this is a
        # taskbar identity thing, unrelated to how the app was launched.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AISMonitor.AISMonitor.1")

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("assets/app_icon.png"))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()