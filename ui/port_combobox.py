from PySide6.QtWidgets import QComboBox
import serial.tools.list_ports


class PortComboBox(QComboBox):

    def refresh_ports(self):
        current = self.currentText()

        self.clear()

        # Numeric sort on the COM number, not lexicographic — otherwise
        # COM10 would sort before COM2. Non-COM device names (Linux/Mac
        # style, e.g. /dev/ttyUSB0) just fall to the end of the list.
        ports = sorted(
            [p.device for p in serial.tools.list_ports.comports()],
            key=lambda x: int(x.replace("COM", "")) if x.startswith("COM") else 999999
        )

        self.addItems(ports)

        index = self.findText(current)

        if index >= 0:
            self.setCurrentIndex(index)

    def showPopup(self):

        # Re-scan right before the dropdown opens rather than only once at
        # startup, so a receiver plugged in after launch actually shows up.
        self.refresh_ports()

        super().showPopup()