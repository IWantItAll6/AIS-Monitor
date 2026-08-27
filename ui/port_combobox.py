from PyQt6.QtWidgets import QComboBox
import serial.tools.list_ports


class PortComboBox(QComboBox):

    def refresh_ports(self):
        current = self.currentText()

        self.clear()

        ports = sorted(
            [p.device for p in serial.tools.list_ports.comports()],
            key=lambda x: int(x.replace("COM", "")) if x.startswith("COM") else 999999
        )

        self.addItems(ports)

        index = self.findText(current)

        if index >= 0:
            self.setCurrentIndex(index)

    def showPopup(self):

        self.refresh_ports()

        super().showPopup()