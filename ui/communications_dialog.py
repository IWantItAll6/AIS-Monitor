from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QLabel,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QPushButton,
    QWidget
)

from ui.port_combobox import PortComboBox

# bytesize, parity, stopbits — pyserial's own vocabulary, matching how this
# is written on the datasheet (e.g. "8E1"): 8 data bits, Even parity, 1 stop bit.
SERIAL_FORMATS = ["8N1", "8E1", "8O1", "7E1", "7O1"]


class CommunicationsDialog(QDialog):

    def __init__(self, settings):

        super().__init__()

        self.settings = settings

        self.setWindowTitle("Communications")

        self.setup_ui()

        self.load_settings()

    def setup_ui(self):

        layout = QVBoxLayout()

        self.setLayout(layout)

        #
        # AIS
        #

        ais_title = QLabel("AIS Receiver")

        font = ais_title.font()
        font.setBold(True)

        ais_title.setFont(font)

        layout.addWidget(ais_title)

        ais_form = QFormLayout()

        self.ais_port = PortComboBox()
        self.ais_port.refresh_ports()

        self.ais_baud = QComboBox()
        self.ais_baud.addItems(["4800", "9600", "19200", "38400", "57600", "115200"])

        ais_form.addRow("AIS Port", self.ais_port)
        ais_form.addRow("AIS Baud", self.ais_baud)

        layout.addLayout(ais_form)

        layout.addSpacing(10)

        #
        # GNSS
        #

        gnss_title = QLabel("GNSS Receiver")

        font = gnss_title.font()
        font.setBold(True)

        gnss_title.setFont(font)

        layout.addWidget(gnss_title)

        gnss_form = QFormLayout()

        self.use_separate_gnss = QCheckBox()

        self.gnss_port = PortComboBox()
        self.gnss_port.refresh_ports()

        self.gnss_baud = QComboBox()
        self.gnss_baud.addItems(["4800", "9600", "19200", "38400", "57600", "115200"])

        gnss_form.addRow("Use Separate GNSS", self.use_separate_gnss)
        gnss_form.addRow("GNSS Port", self.gnss_port)
        gnss_form.addRow("GNSS Baud", self.gnss_baud)

        layout.addLayout(gnss_form)

        self.use_separate_gnss.stateChanged.connect(self.update_gnss_controls)

        layout.addSpacing(10)

        #
        # ADVANCED (collapsed by default — 8N1 covers most cases)
        #

        self.advanced_toggle = QPushButton("► Advanced")

        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.clicked.connect(self.toggle_advanced)

        layout.addWidget(self.advanced_toggle)

        self.advanced_widget = QWidget()

        advanced_form = QFormLayout()
        self.advanced_widget.setLayout(advanced_form)

        self.ais_serial_format = QComboBox()
        self.ais_serial_format.addItems(SERIAL_FORMATS)

        self.gnss_serial_format = QComboBox()
        self.gnss_serial_format.addItems(SERIAL_FORMATS)

        advanced_form.addRow("AIS Serial Format (data/parity/stop)", self.ais_serial_format)
        advanced_form.addRow("GNSS Serial Format (data/parity/stop)", self.gnss_serial_format)

        self.advanced_widget.hide()

        layout.addWidget(self.advanced_widget)

        self.update_gnss_controls()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(buttons)

    def update_gnss_controls(self):

        enabled = self.use_separate_gnss.isChecked()

        self.gnss_port.setEnabled(enabled)
        self.gnss_baud.setEnabled(enabled)
        self.gnss_serial_format.setEnabled(enabled)

    def toggle_advanced(self):

        if self.advanced_toggle.isChecked():

            self.advanced_toggle.setText("▼ Advanced")
            self.advanced_widget.show()

        else:

            self.advanced_toggle.setText("► Advanced")
            self.advanced_widget.hide()

    def load_settings(self):
        self.ais_port.setCurrentText(self.settings["ais_port"])
        self.ais_baud.setCurrentText(self.settings["ais_baud"])

        self.use_separate_gnss.setChecked(self.settings["use_separate_gnss"])

        self.gnss_port.setCurrentText(self.settings["gnss_port"])
        self.gnss_baud.setCurrentText(self.settings["gnss_baud"])

        self.ais_serial_format.setCurrentText(self.settings["ais_serial_format"])
        self.gnss_serial_format.setCurrentText(self.settings["gnss_serial_format"])

    def save_settings(self):
        self.settings["ais_port"] = self.ais_port.currentText()
        self.settings["ais_baud"] = self.ais_baud.currentText()

        self.settings["use_separate_gnss"] = self.use_separate_gnss.isChecked()

        self.settings["gnss_port"] = self.gnss_port.currentText()
        self.settings["gnss_baud"] = self.gnss_baud.currentText()

        self.settings["ais_serial_format"] = self.ais_serial_format.currentText()
        self.settings["gnss_serial_format"] = self.gnss_serial_format.currentText()

    def accept(self):
        self.save_settings()

        super().accept()
