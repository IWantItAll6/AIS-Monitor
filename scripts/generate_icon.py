"""
Generates the application icon programmatically, reusing MapPanel's own
color palette (navy water, green land, orange vessel) so the icon reads as
"this app" rather than generic clip art. Re-run this after changing the
design; it overwrites assets/app_icon.png.
"""

import random

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPainter, QColor, QPixmap, QPolygonF, QPainterPath
from PySide6.QtCore import Qt, QPointF, QRectF

SIZE = 256

WATER_COLOR = QColor(20, 40, 60)
LAND_COLOR = QColor(60, 90, 50)
VESSEL_COLOR = QColor(255, 140, 0)

# MapPanel draws a real AtoN in the same (configurable) vessel color as a
# ship, distinguished by shape alone — matching that here, rather than
# picking a color of its own, keeps the icon truthful to what the app
# actually renders.
ATON_COLOR = VESSEL_COLOR


def jagged_curve_points(p0, control, p1, segments=14, jitter=7, seed=0):
    """Samples a quadratic bezier, then perturbs each interior point
    perpendicular to the curve — connecting these with straight lines
    (instead of drawing the bezier itself) gives a rugged, many-small-
    segments coastline look, the same way real coastline data (and this
    app's own map) is just a lot of short straight segments, not smooth
    curves."""

    rng = random.Random(seed)
    points = []

    for i in range(segments + 1):

        t = i / segments

        x = (1 - t) ** 2 * p0.x() + 2 * (1 - t) * t * control.x() + t ** 2 * p1.x()
        y = (1 - t) ** 2 * p0.y() + 2 * (1 - t) * t * control.y() + t ** 2 * p1.y()

        # Endpoints stay exact so consecutive shoreline pieces still meet
        # up cleanly — only interior points get jittered.
        if 0 < i < segments:

            dx = 2 * (1 - t) * (control.x() - p0.x()) + 2 * t * (p1.x() - control.x())
            dy = 2 * (1 - t) * (control.y() - p0.y()) + 2 * t * (p1.y() - control.y())

            length = (dx ** 2 + dy ** 2) ** 0.5 or 1
            nx, ny = -dy / length, dx / length

            offset = rng.uniform(-jitter, jitter)
            x += nx * offset
            y += ny * offset

        points.append(QPointF(x, y))

    return points


def generate():

    app = QApplication.instance() or QApplication([])

    pixmap = QPixmap(SIZE, SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Rounded-square background, matching the map's water color.
    background = QPainterPath()
    background.addRoundedRect(QRectF(0, 0, SIZE, SIZE), 48, 48)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(WATER_COLOR)
    painter.drawPath(background)

    # A river mouth rather than a constant-width strait: two banks that
    # start close together near the bottom-left (the "river"), then curve
    # apart, opening into a broad mouth across the top-right corner (the
    # "sea") — the vessel sails out of the narrow end toward the open
    # water. Both banks are smaller than a full corner-triangle and curved
    # (quadTo, not straight lines), so less of the icon is land and the
    # coastline doesn't read as geometric.
    painter.setClipPath(background)
    painter.setBrush(LAND_COLOR)

    # North bank — the top-left landmass. Meets the top edge partway
    # across, curves down to a point just off the bottom-left corner.
    north_bank = QPainterPath()
    north_bank.moveTo(0, 0)
    north_bank.lineTo(SIZE * 0.42, 0)

    for point in jagged_curve_points(
        QPointF(SIZE * 0.42, 0), QPointF(SIZE * 0.24, SIZE * 0.33), QPointF(SIZE * 0.05, SIZE * 0.80),
        seed=1
    )[1:]:
        north_bank.lineTo(point)

    north_bank.lineTo(0, SIZE * 0.80)
    north_bank.closeSubpath()

    painter.drawPath(north_bank)

    # South bank — the bottom-right landmass. Meets the right edge partway
    # up, curves down to a point just off the bottom-left corner, close to
    # (but not touching) the north bank's point — that gap is the narrow
    # "river" end.
    south_bank = QPainterPath()
    south_bank.moveTo(SIZE, SIZE)
    south_bank.lineTo(SIZE, SIZE * 0.55)

    for point in jagged_curve_points(
        QPointF(SIZE, SIZE * 0.55), QPointF(SIZE * 0.45, SIZE * 0.62), QPointF(SIZE * 0.16, SIZE * 0.90),
        seed=2
    )[1:]:
        south_bank.lineTo(point)

    south_bank.lineTo(SIZE * 0.16, SIZE)
    south_bank.closeSubpath()

    painter.drawPath(south_bank)

    painter.setClipping(False)

    # The vessel triangle itself — same shape used on the map, scaled up
    # and narrowed so it reads as a ship heading somewhere, not a play
    # button — sailing out of the narrow river end toward the open mouth.
    triangle = QPolygonF([
        QPointF(0, -46),
        QPointF(18, 38),
        QPointF(-18, 38)
    ])

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(VESSEL_COLOR)
    painter.save()
    painter.translate(SIZE * 0.24, SIZE * 0.62)
    painter.rotate(45)
    painter.drawPolygon(triangle)
    painter.restore()

    # A small Aid to Navigation marking the mouth's entrance — the same
    # diamond shape MapPanel draws for a real AtoN, out in the open water
    # the vessel is heading toward, tying the icon to a marker the app
    # actually renders rather than being purely decorative.
    aton_half = 12
    aton_center = QPointF(SIZE * 0.74, SIZE * 0.24)
    aton_diamond = QPolygonF([
        aton_center + QPointF(0, -aton_half), aton_center + QPointF(aton_half, 0),
        aton_center + QPointF(0, aton_half), aton_center + QPointF(-aton_half, 0),
    ])

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ATON_COLOR)
    painter.drawPolygon(aton_diamond)

    painter.end()

    pixmap.save("assets/app_icon.png", "PNG")

    print("Saved assets/app_icon.png")


if __name__ == "__main__":
    generate()
