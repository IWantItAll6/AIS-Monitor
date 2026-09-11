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
    QWidget,
    QLineEdit,
    QMessageBox,
    QSpacerItem
)
from PySide6.QtGui import QIntValidator

from ui.port_combobox import PortComboBox
from services.serial_reader import SerialTestThread
from services.network_reader import NetworkTestThread

AIS_SOURCE_TYPES = ["Serial", "Network"]

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

    def add_section_title(self, form, text, spacing_above=True):
        """A bold, full-width row inside `form` marking the start of a
        section — kept as a row in the same shared QFormLayout as its
        section's fields (rather than a separate QLabel added directly to
        the dialog's outer layout) so every section's fields size against
        the exact same label/value columns and end up the same width."""

        if spacing_above:
            form.addItem(QSpacerItem(0, 10))

        title = QLabel(text)

        font = title.font()
        font.setBold(True)
        title.setFont(font)

        form.addRow(title)

    def setup_ui(self):

        layout = QVBoxLayout()

        self.setLayout(layout)

        # AIS, GNSS, and Network Broadcast all share one QFormLayout —
        # Qt sizes a form's label/value columns per QFormLayout instance,
        # so splitting these into separate layouts (as this dialog used to)
        # let each section's, and each source's, fields end up a visibly
        # different width from its neighbors (e.g. "AIS Source" narrower
        # than "AIS Port"/"AIS Baud", or the AIS section's fields wider
        # than GNSS's, since "Use Separate GNSS" is a long label). One
        # shared form makes every field the same width, full stop.
        form = QFormLayout()

        #
        # AIS
        #

        self.add_section_title(form, "AIS Receiver", spacing_above=False)

        # Serial (COM port) and Network (TCP) are mutually exclusive ways to
        # get AIS data in — some receivers expose their data over WiFi
        # instead of, not in addition to, a serial port. Only the rows for
        # whichever source is selected are shown at a time (setRowVisible,
        # see update_ais_source_controls) — both stay part of this one form.
        self.ais_source_type = QComboBox()
        self.ais_source_type.addItems(AIS_SOURCE_TYPES)
        self.ais_source_type.currentTextChanged.connect(self.update_ais_source_controls)

        form.addRow("AIS Source", self.ais_source_type)

        self.ais_port = PortComboBox()
        self.ais_port.refresh_ports()

        self.ais_baud = QComboBox()
        self.ais_baud.addItems(["4800", "9600", "19200", "38400", "57600", "115200"])

        form.addRow("AIS Port", self.ais_port)
        form.addRow("AIS Baud", self.ais_baud)

        self.ais_test_button = QPushButton("Test")
        self.ais_test_status = QLabel("")

        ais_test_row = QHBoxLayout()
        ais_test_row.addWidget(self.ais_test_button)
        ais_test_row.addWidget(self.ais_test_status, 1)

        form.addRow("", ais_test_row)

        self.ais_test_button.clicked.connect(lambda: self.run_test("ais"))

        self.ais_network_host = QLineEdit()
        self.ais_network_host.setPlaceholderText("e.g. 192.168.4.1")

        self.ais_network_port = QLineEdit()
        self.ais_network_port.setValidator(QIntValidator(1, 65535))

        form.addRow("Host", self.ais_network_host)
        form.addRow("Port", self.ais_network_port)

        self.ais_network_test_button = QPushButton("Test")
        self.ais_network_test_status = QLabel("")

        ais_network_test_row = QHBoxLayout()
        ais_network_test_row.addWidget(self.ais_network_test_button)
        ais_network_test_row.addWidget(self.ais_network_test_status, 1)

        form.addRow("", ais_network_test_row)

        self.ais_network_test_button.clicked.connect(self.run_network_test)

        # Rows toggled by update_ais_source_controls() based on which source
        # is selected — kept together so that method doesn't need to know
        # the row layout details, just which rows exist per source.
        self._ais_serial_rows = [self.ais_port, self.ais_baud, ais_test_row]
        self._ais_network_rows = [self.ais_network_host, self.ais_network_port, ais_network_test_row]

        #
        # GNSS
        #

        self.add_section_title(form, "GNSS Receiver")

        self.use_separate_gnss = QCheckBox()

        self.gnss_port = PortComboBox()
        self.gnss_port.refresh_ports()

        self.gnss_baud = QComboBox()
        self.gnss_baud.addItems(["4800", "9600", "19200", "38400", "57600", "115200"])

        form.addRow("Use Separate GNSS", self.use_separate_gnss)
        form.addRow("GNSS Port", self.gnss_port)
        form.addRow("GNSS Baud", self.gnss_baud)

        self.gnss_test_button = QPushButton("Test")
        self.gnss_test_status = QLabel("")

        gnss_test_row = QHBoxLayout()
        gnss_test_row.addWidget(self.gnss_test_button)
        gnss_test_row.addWidget(self.gnss_test_status, 1)

        form.addRow("", gnss_test_row)

        self.gnss_test_button.clicked.connect(lambda: self.run_test("gnss"))

        self.use_separate_gnss.stateChanged.connect(self.update_gnss_controls)

        #
        # NETWORK BROADCAST
        #

        self.add_section_title(form, "Network Broadcast")

        self.broadcast_enabled = QCheckBox()

        self.broadcast_port = QLineEdit()
        self.broadcast_port.setValidator(QIntValidator(1, 65535))

        form.addRow("Broadcast NMEA over TCP", self.broadcast_enabled)
        form.addRow("TCP Port", self.broadcast_port)

        self.broadcast_enabled.toggled.connect(self.broadcast_port.setEnabled)

        self._form = form

        layout.addLayout(form)

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
        self.update_ais_source_controls()

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

    def update_ais_source_controls(self):

        is_network = self.ais_source_type.currentText() == "Network"

        for row in self._ais_serial_rows:
            self._form.setRowVisible(row, not is_network)

        for row in self._ais_network_rows:
            self._form.setRowVisible(row, is_network)

        # Irrelevant to a network source — Advanced may not have been built
        # yet the first time this runs (called once from setup_ui before
        # the Advanced section further down exists).
        if hasattr(self, "ais_serial_format"):
            self.ais_serial_format.setEnabled(not is_network)

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

    def run_network_test(self):

        host = self.ais_network_host.text().strip()
        port_text = self.ais_network_port.text().strip()

        if not host or not port_text:
            self.ais_network_test_status.setText("✗ Enter a host and port")
            return

        self.ais_network_test_button.setEnabled(False)
        self.ais_network_test_status.setText(f"Testing (listening up to {NetworkTestThread.DURATION_SECONDS}s)…")

        thread = NetworkTestThread(host, int(port_text))

        # Kept on self, not a local var, for the same reason as
        # ais_test_thread/gnss_test_thread above.
        self.ais_network_test_thread = thread

        thread.test_finished.connect(self.on_network_test_finished)
        thread.start()

    def on_network_test_finished(self, result):

        button, status = self.ais_network_test_button, self.ais_network_test_status

        button.setEnabled(True)

        if not result["success"]:
            status.setText(f"✗ Could not connect: {result['error']}")
            return

        byte_count = result["byte_count"]

        if byte_count == 0:
            status.setText(
                f"✗ Connected but no data received in "
                f"{NetworkTestThread.DURATION_SECONDS}s — check host/port"
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
                f"({result['printable_ratio']:.0%} printable) — check host/port"
            )

    def load_settings(self):
        self.ais_port.setCurrentText(self.settings["ais_port"])
        self.ais_baud.setCurrentText(self.settings["ais_baud"])

        self.ais_source_type.setCurrentText(self.settings.get("ais_source_type", "Serial"))
        self.ais_network_host.setText(self.settings.get("ais_network_host", ""))
        self.ais_network_port.setText(str(self.settings.get("ais_network_port", "10110")))
        self.update_ais_source_controls()

        self.use_separate_gnss.setChecked(self.settings["use_separate_gnss"])

        self.gnss_port.setCurrentText(self.settings["gnss_port"])
        self.gnss_baud.setCurrentText(self.settings["gnss_baud"])

        self.ais_serial_format.setCurrentText(self.settings["ais_serial_format"])
        self.gnss_serial_format.setCurrentText(self.settings["gnss_serial_format"])

        self.broadcast_enabled.setChecked(self.settings["broadcast_enabled"])
        self.broadcast_port.setText(str(self.settings["broadcast_port"]))
        self.broadcast_port.setEnabled(self.settings["broadcast_enabled"])

    def save_settings(self):
        self.settings["ais_port"] = self.ais_port.currentText()
        self.settings["ais_baud"] = self.ais_baud.currentText()

        self.settings["ais_source_type"] = self.ais_source_type.currentText()
        self.settings["ais_network_host"] = self.ais_network_host.text().strip()
        self.settings["ais_network_port"] = self.ais_network_port.text()

        self.settings["use_separate_gnss"] = self.use_separate_gnss.isChecked()

        self.settings["gnss_port"] = self.gnss_port.currentText()
        self.settings["gnss_baud"] = self.gnss_baud.currentText()

        self.settings["ais_serial_format"] = self.ais_serial_format.currentText()
        self.settings["gnss_serial_format"] = self.gnss_serial_format.currentText()

        self.settings["broadcast_enabled"] = self.broadcast_enabled.isChecked()
        self.settings["broadcast_port"] = self.broadcast_port.text()

    def accept(self):

        if self.ais_source_type.currentText() == "Network" and not (
            self.ais_network_host.text().strip() and self.ais_network_port.text()
        ):
            QMessageBox.warning(self, "AIS Source", "Enter a host and port for the network AIS source, or switch back to Serial.")
            return

        if self.broadcast_enabled.isChecked() and not self.broadcast_port.text():
            QMessageBox.warning(self, "Network Broadcast", "Enter a TCP port to broadcast on, or disable broadcasting.")
            return

        self.save_settings()

        super().accept()

    def done(self, result):

        # Covers OK, Cancel, and the window's X button alike (QDialog routes
        # all three through here) — waits out a still-running test thread
        # rather than letting its Python wrapper get garbage-collected while
        # the QThread is active, the same "destroyed while running" crash
        # class already hit once elsewhere in this app's serial handling.
        test_threads = (
            getattr(self, "ais_test_thread", None),
            getattr(self, "gnss_test_thread", None),
            getattr(self, "ais_network_test_thread", None),
        )

        for thread in test_threads:

            if thread is not None and thread.isRunning():
                thread.wait(thread.DURATION_SECONDS * 1000 + 2000)

        super().done(result)
