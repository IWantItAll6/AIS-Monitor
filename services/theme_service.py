import ctypes
import platform

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor


def apply_theme(app, theme_name):

    # Fusion respects a custom QPalette consistently across widgets — the
    # native Windows style ignores palette colors for some controls, which
    # would leave a dark theme half-applied.
    app.setStyle("Fusion")

    # PySide6/Qt 6.8+'s Fusion style became OS-color-scheme-aware: with no
    # explicit QStyleHints.colorScheme set, both build_dark_palette() and
    # (previously) app.style().standardPalette() get quietly overridden
    # back towards whatever Windows' own theme setting is. On a machine set
    # to OS dark mode, that made picking "Light" here produce a palette
    # that was still dark. Pinning the hint explicitly, in addition to
    # setting an explicit palette for both themes, makes the app's own
    # choice win regardless of the OS setting.
    color_scheme = Qt.ColorScheme.Dark if theme_name == "Dark" else Qt.ColorScheme.Light
    app.styleHints().setColorScheme(color_scheme)

    if theme_name == "Dark":
        app.setPalette(build_dark_palette())

    else:
        app.setPalette(build_light_palette())


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


def build_light_palette():

    # Explicit colors rather than app.style().standardPalette() — on Qt
    # 6.8+, Fusion's "standard" palette follows the OS color-scheme hint,
    # so on a machine set to Windows dark mode it was no longer a fixed
    # light-gray palette. Mirrors build_dark_palette()'s classic Fusion
    # light look (the same values Fusion used before it became
    # OS-scheme-aware).

    palette = QPalette()

    palette.setColor(QPalette.ColorRole.Window, QColor(240, 240, 240))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(233, 233, 233))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 220))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.Text, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.Button, QColor(240, 240, 240))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(200, 0, 0))
    palette.setColor(QPalette.ColorRole.Link, QColor(0, 90, 190))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(48, 140, 198))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))

    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(150, 150, 150))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(150, 150, 150))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(150, 150, 150))

    return palette
