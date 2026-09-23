from PySide6.QtWidgets import QComboBox
import serial.tools.list_ports


def _registry_serial_ports():
    """Some virtual-port drivers (e.g. com0com) don't always surface their
    pairs through pyserial's WMI/SetupAPI-based comports() scan, but every
    live COM port — real or virtual — is registered under this key, since
    it's the canonical list Windows itself uses. Read as a best-effort
    fallback, unioned with comports() below rather than replacing it."""

    try:
        import winreg

        ports = []

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as key:

            i = 0

            while True:
                try:
                    _, value, _ = winreg.EnumValue(key, i)
                    ports.append(value)
                    i += 1

                except OSError:
                    break

        return ports

    except (ImportError, OSError):
        return []


class PortComboBox(QComboBox):

    def refresh_ports(self):
        current = self.currentText()

        self.clear()

        device_names = {p.device for p in serial.tools.list_ports.comports()}
        device_names.update(_registry_serial_ports())

        # Numeric sort on the COM number, not lexicographic — otherwise
        # COM10 would sort before COM2. Non-COM device names (Linux/Mac
        # style, e.g. /dev/ttyUSB0) just fall to the end of the list.
        ports = sorted(
            device_names,
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