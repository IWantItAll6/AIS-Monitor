import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

from ui.main_window import MainWindow


def main():

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