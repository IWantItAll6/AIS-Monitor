from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QPushButton,
    QWidget
)

from ui.port_combobox import PortComboBox
from services.serial_reader import SerialTestThread

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

        self.ais_test_button = QPushButton("Test")
        self.ais_test_status = QLabel("")

        ais_test_row = QHBoxLayout()
        ais_test_row.addWidget(self.ais_test_button)
        ais_test_row.addWidget(self.ais_test_status, 1)

        ais_form.addRow("", ais_test_row)

        self.ais_test_button.clicked.connect(lambda: self.run_test("ais"))

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

        self.gnss_test_button = QPushButton("Test")
        self.gnss_test_status = QLabel("")

        gnss_test_row = QHBoxLayout()
        gnss_test_row.addWidget(self.gnss_test_button)
        gnss_test_row.addWidget(self.gnss_test_status, 1)

        gnss_form.addRow("", gnss_test_row)

        self.gnss_test_button.clicked.connect(lambda: self.run_test("gnss"))

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
        self.gnss_test_button.setEnabled(enabled)

    def toggle_advanced(self):

        if self.advanced_toggle.isChecked():

            self.advanced_toggle.setText("▼ Advanced")
            self.advanced_widget.show()

        else:

            self.advanced_toggle.setText("► Advanced")
            self.advanced_widget.hide()

    def run_test(self, which):

        if which == "ais":
            port, baud, serial_format = self.ais_port, self.ais_baud, self.ais_serial_format
            button, status = self.ais_test_button, self.ais_test_status

        else:
            port, baud, serial_format = self.gnss_port, self.gnss_baud, self.gnss_serial_format
            button, status = self.gnss_test_button, self.gnss_test_status

        port_name = port.currentText()

        if not port_name:
            status.setText("✗ No port selected")
            return

        button.setEnabled(False)
        status.setText(f"Testing (listening up to {SerialTestThread.DURATION_SECONDS}s)…")

        thread = SerialTestThread(port_name, baud.currentText(), serial_format.currentText())

        # Kept on self (not a local var) so it isn't garbage-collected while
        # still running — a QThread whose Python wrapper disappears mid-run
        # is a real crash risk, not just a theoretical one.
        if which == "ais":
            self.ais_test_thread = thread
        else:
            self.gnss_test_thread = thread

        thread.test_finished.connect(lambda result: self.on_test_finished(which, result))
        thread.start()

    def on_test_finished(self, which, result):

        if which == "ais":
            button, status = self.ais_test_button, self.ais_test_status
        else:
            button, status = self.gnss_test_button, self.gnss_test_status

        button.setEnabled(True)

        if not result["success"]:
            status.setText(f"✗ Could not open port: {result['error']}")
            return

        byte_count = result["byte_count"]

        if byte_count == 0:
            status.setText(
                f"✗ Port opened but no data received in "
                f"{SerialTestThread.DURATION_SECONDS}s — check cable/power/port"
            )

        elif result["found_nmea"]:
            status.setText(f"✓ Valid NMEA sentence seen ({byte_count} bytes) — looks good")

        elif result["printable_ratio"] > 0.9:
            status.setText(
                f"✓ Received {byte_count} bytes of normal-looking characters "
                "(no full sentence caught in this short a window, but that's expected sometimes)"
            )

        else:
            status.setText(
                f"⚠ Received {byte_count} bytes but they look garbled "
                f"({result['printable_ratio']:.0%} printable) — check baud/parity"
            )

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

    def done(self, result):

        # Covers OK, Cancel, and the window's X button alike (QDialog routes
        # all three through here) — waits out a still-running test thread
        # rather than letting its Python wrapper get garbage-collected while
        # the QThread is active, the same "destroyed while running" crash
        # class already hit once elsewhere in this app's serial handling.
        for thread in (getattr(self, "ais_test_thread", None), getattr(self, "gnss_test_thread", None)):

            if thread is not None and thread.isRunning():
                thread.wait(SerialTestThread.DURATION_SECONDS * 1000 + 2000)

        super().done(result)
