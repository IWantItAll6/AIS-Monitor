"""
Generates the application icon programmatically, reusing MapPanel's own
color palette (navy water, green land, orange vessel) so the icon reads as
"this app" rather than generic clip art. Re-run this after changing the
design; it overwrites assets/app_icon.png.
"""

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPainter, QColor, QPixmap, QPolygonF, QPainterPath
from PyQt6.QtCore import Qt, QPointF, QRectF

SIZE = 256

WATER_COLOR = QColor(20, 40, 60)
LAND_COLOR = QColor(60, 90, 50)
VESSEL_COLOR = QColor(255, 140, 0)
RING_COLOR = QColor(120, 160, 180, 90)


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

    # A corner of coastline, bottom-left — echoes the map view.
    land = QPainterPath()
    land.moveTo(0, SIZE * 0.62)
    land.cubicTo(SIZE * 0.18, SIZE * 0.52, SIZE * 0.30, SIZE * 0.78, SIZE * 0.46, SIZE * 0.70)
    land.cubicTo(SIZE * 0.30, SIZE * 0.90, SIZE * 0.15, SIZE * 0.95, 0, SIZE * 0.92)
    land.closeSubpath()

    painter.setBrush(LAND_COLOR)
    painter.drawPath(land)

    # Radar-style rings behind the vessel, subtle.
    painter.setPen(RING_COLOR)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    center = QPointF(SIZE * 0.58, SIZE * 0.42)

    for radius in (40, 65, 90):
        painter.drawEllipse(center, radius, radius)

    # The vessel triangle itself — same shape used on the map, scaled up
    # and narrowed so it reads as a ship heading somewhere, not a play button.
    triangle = QPolygonF([
        QPointF(0, -50),
        QPointF(20, 42),
        QPointF(-20, 42)
    ])

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(VESSEL_COLOR)
    painter.save()
    painter.translate(center)
    painter.rotate(20)
    painter.drawPolygon(triangle)
    painter.restore()

    painter.end()

    pixmap.save("assets/app_icon.png", "PNG")

    print("Saved assets/app_icon.png")


if __name__ == "__main__":
    generate()
