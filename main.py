import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

from ui.main_window import MainWindow


def main():

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("assets/app_icon.png"))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()