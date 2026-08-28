from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QDialogButtonBox,
    QFileDialog
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
        # Units
        #

        units_title = QLabel("Units")

        font = units_title.font()
        font.setBold(True)

        units_title.setFont(font)

        layout.addWidget(units_title)

        units_form = QFormLayout()

        self.distance_unit = QComboBox()
        self.distance_unit.addItems(["NM", "Miles", "Km"])

        units_form.addRow("Distance", self.distance_unit)

        layout.addLayout(units_form)

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

        #
        # Recording
        #

        recording_title = QLabel("Recording")

        font = recording_title.font()
        font.setBold(True)

        recording_title.setFont(font)

        layout.addWidget(recording_title)

        recording_form = QFormLayout()

        self.recordings_folder = QLineEdit()
        self.recordings_folder.setReadOnly(True)

        self.browse_recordings_button = QPushButton("Browse...")
        self.browse_recordings_button.clicked.connect(self.browse_recordings_folder)

        recordings_folder_row = QHBoxLayout()
        recordings_folder_row.addWidget(self.recordings_folder, 1)
        recordings_folder_row.addWidget(self.browse_recordings_button)

        recording_form.addRow("Recordings Folder", recordings_folder_row)

        self.recordings_warning_size = QComboBox()
        self.recordings_warning_size.addItems(["100", "250", "500", "1000", "2000", "No warning"])
        self.recordings_warning_size.setCurrentText("500")

        recording_form.addRow("Warn When Recordings Folder Exceeds (MB)", self.recordings_warning_size)

        layout.addLayout(recording_form)

        layout.addSpacing(10)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(buttons)

    def browse_recordings_folder(self):

        start_dir = self.recordings_folder.text() or "data/recordings"

        folder = QFileDialog.getExistingDirectory(self, "Choose Recordings Folder", start_dir)

        if folder:
            self.recordings_folder.setText(folder)

    def load_settings(self):
        self.theme.setCurrentText(self.settings["theme"])

        self.distance_unit.setCurrentText(self.settings["distance_unit"])

        self.vessel_timeout.setCurrentText(self.settings["vessel_timeout"])
        self.track_length.setCurrentText(self.settings["track_length"])

        self.recordings_folder.setText(self.settings["recordings_folder"])
        self.recordings_warning_size.setCurrentText(self.settings["recordings_warning_size_mb"])

    def save_settings(self):
        self.settings["theme"] = self.theme.currentText()

        self.settings["distance_unit"] = self.distance_unit.currentText()

        self.settings["vessel_timeout"] = self.vessel_timeout.currentText()
        self.settings["track_length"] = self.track_length.currentText()

        self.settings["recordings_folder"] = self.recordings_folder.text()
        self.settings["recordings_warning_size_mb"] = self.recordings_warning_size.currentText()

    def accept(self):
        self.save_settings()

        super().accept()
