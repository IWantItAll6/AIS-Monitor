import ctypes
import platform

from PySide6.QtGui import QPalette, QColor


def apply_theme(app, theme_name):

    # Fusion respects a custom QPalette consistently across widgets — the
    # native Windows style ignores palette colors for some controls, which
    # would leave a dark theme half-applied.
    app.setStyle("Fusion")

    if theme_name == "Dark":
        app.setPalette(build_dark_palette())

    else:
        app.setPalette(app.style().standardPalette())


def apply_title_bar_theme(window, theme_name):

    # The OS-drawn title bar isn't a Qt widget — QPalette can't touch it.
    # Windows only exposes dark-mode title bars via this DWM attribute.
    if platform.system() != "Windows":
        return

    try:
        hwnd = int(window.winId())
        enabled = ctypes.c_int(1 if theme_name == "Dark" else 0)

        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE on Windows 11 / Windows 10
        # 2004+; older Windows 10 builds only recognize attribute 19.
        for attribute in (20, 19):

            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)
            )

            if result == 0:
                break

    except Exception:
        pass


def build_dark_palette():

    palette = QPalette()

    palette.setColor(QPalette.ColorRole.Window, QColor(45, 45, 48))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(45, 45, 48))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 48))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 80, 80))
    palette.setColor(QPalette.ColorRole.Link, QColor(100, 160, 220))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(60, 110, 180))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))

    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(120, 120, 120))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(120, 120, 120))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(120, 120, 120))

    return palette
