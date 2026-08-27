from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QLabel,
    QComboBox,
    QDialogButtonBox
)


class PreferencesDialog(QDialog):

    def __init__(self, settings):

        super().__init__()

        self.settings = settings

        self.setWindowTitle("Preferences")

        self.setup_ui()

        self.load_settings()

    def setup_ui(self):

        layout = QVBoxLayout()

        self.setLayout(layout)

        #
        # Appearance
        #

        appearance_title = QLabel("Appearance")

        font = appearance_title.font()
        font.setBold(True)

        appearance_title.setFont(font)

        layout.addWidget(appearance_title)

        appearance_form = QFormLayout()

        self.theme = QComboBox()
        self.theme.addItems(["Dark", "Light"])

        appearance_form.addRow("Theme", self.theme)

        layout.addLayout(appearance_form)

        layout.addSpacing(10)

        #
        # Vessel Management
        #

        vessel_title = QLabel("Vessel Management")

        font = vessel_title.font()
        font.setBold(True)

        vessel_title.setFont(font)

        layout.addWidget(vessel_title)

        vessel_form = QFormLayout()

        self.vessel_timeout = QComboBox()
        self.vessel_timeout.addItems(["1", "5", "10", "30", "60", "Unlimited"])
        self.vessel_timeout.setCurrentText("10")

        self.track_length = QComboBox()
        self.track_length.addItems(["1", "5", "10", "30", "60", "Unlimited"])
        self.track_length.setCurrentText("10")

        vessel_form.addRow("Vessel Timeout (mins)", self.vessel_timeout)
        vessel_form.addRow("Track Length (mins)", self.track_length)

        layout.addLayout(vessel_form)

        layout.addSpacing(10)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(buttons)

    def load_settings(self):
        self.theme.setCurrentText(self.settings["theme"])

        self.vessel_timeout.setCurrentText(self.settings["vessel_timeout"])
        self.track_length.setCurrentText(self.settings["track_length"])

    def save_settings(self):
        self.settings["theme"] = self.theme.currentText()

        self.settings["vessel_timeout"] = self.vessel_timeout.currentText()
        self.settings["track_length"] = self.track_length.currentText()

    def accept(self):
        self.save_settings()

        super().accept()
