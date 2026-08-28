"""
Generates the application icon programmatically, reusing MapPanel's own
color palette (navy water, green land, orange vessel) so the icon reads as
"this app" rather than generic clip art. Re-run this after changing the
design; it overwrites assets/app_icon.png.
"""

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPainter, QColor, QPixmap, QPolygonF, QPainterPath
from PySide6.QtCore import Qt, QPointF, QRectF

SIZE = 256

WATER_COLOR = QColor(20, 40, 60)
LAND_COLOR = QColor(60, 90, 50)
VESSEL_COLOR = QColor(255, 140, 0)


def generate():

    app = QApplication.instance() or QApplication([])

    pixmap = QPixmap(SIZE, SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Rounded-square background, matching the map's water color.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(WATER_COLOR)
    painter.drawRoundedRect(QRectF(0, 0, SIZE, SIZE), 48, 48)

    # Two landmasses on opposite corners, mainland (bottom-left) and an
    # island (top-right) — a Solent/Portsmouth-style channel between them,
    # rather than a single coastline corner, so the vessel reads as
    # threading through a strait instead of just floating near a shore.
    painter.setBrush(LAND_COLOR)

    mainland = QPainterPath()
    mainland.moveTo(0, SIZE * 0.55)
    mainland.cubicTo(SIZE * 0.20, SIZE * 0.48, SIZE * 0.32, SIZE * 0.68, SIZE * 0.40, SIZE * 0.66)
    mainland.cubicTo(SIZE * 0.28, SIZE * 0.88, SIZE * 0.14, SIZE * 0.97, 0, SIZE * 0.95)
    mainland.closeSubpath()

    painter.drawPath(mainland)

    island = QPainterPath()
    island.moveTo(SIZE * 1.0, SIZE * 0.42)
    island.cubicTo(SIZE * 0.86, SIZE * 0.30, SIZE * 0.70, SIZE * 0.34, SIZE * 0.64, SIZE * 0.22)
    island.cubicTo(SIZE * 0.80, SIZE * 0.06, SIZE * 0.94, SIZE * 0.02, SIZE * 1.0, SIZE * 0.06)
    island.closeSubpath()

    painter.drawPath(island)

    # The vessel triangle itself — same shape used on the map, scaled up
    # and narrowed so it reads as a ship heading somewhere, not a play
    # button — oriented up-channel (bottom-left to top-right).
    triangle = QPolygonF([
        QPointF(0, -50),
        QPointF(20, 42),
        QPointF(-20, 42)
    ])

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(VESSEL_COLOR)
    painter.save()
    painter.translate(SIZE * 0.42, SIZE * 0.58)
    painter.rotate(45)
    painter.drawPolygon(triangle)
    painter.restore()

    painter.end()

    pixmap.save("assets/app_icon.png", "PNG")

    print("Saved assets/app_icon.png")


if __name__ == "__main__":
    generate()
