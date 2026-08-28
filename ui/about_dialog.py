from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDialogButtonBox
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtCore import Qt

APP_VERSION = "0.1.0"
APP_AUTHOR = "Iwan Croose"


class AboutDialog(QDialog):

    def __init__(self):

        super().__init__()

        self.setWindowTitle("About AIS Monitor")
        self.setWindowIcon(QIcon("assets/app_icon.png"))

        layout = QVBoxLayout()
        self.setLayout(layout)

        header_layout = QHBoxLayout()

        icon_label = QLabel()
        icon_label.setPixmap(QPixmap("assets/app_icon.png").scaled(
            64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ))
        header_layout.addWidget(icon_label)

        title_layout = QVBoxLayout()

        name_label = QLabel("AIS Monitor")
        font = name_label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 3)
        name_label.setFont(font)
        title_layout.addWidget(name_label)

        title_layout.addWidget(QLabel(f"Version {APP_VERSION}"))

        header_layout.addLayout(title_layout)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        layout.addSpacing(10)

        description = QLabel(
            "A desktop AIS and GNSS monitoring tool — live serial receiver input or\n"
            "offline log replay, a target list with range/bearing to your own position,\n"
            "an offline coastline map with vessel plotting and track history, and\n"
            "signal-strength (RSSI) tracking for compatible receiver hardware."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        layout.addSpacing(10)

        layout.addWidget(QLabel(f"Made by {APP_AUTHOR}"))

        layout.addSpacing(10)

        credits = QLabel(
            "Map data: Natural Earth (public domain).\n"
            "UK place data: GeoNames (CC BY 4.0, https://www.geonames.org/)."
        )
        credits_font = credits.font()
        credits_font.setPointSize(max(credits_font.pointSize() - 1, 7))
        credits.setFont(credits_font)
        layout.addWidget(credits)

        layout.addSpacing(10)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)

        layout.addWidget(buttons)
