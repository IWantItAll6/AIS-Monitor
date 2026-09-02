from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent

from ui.main_window import MainWindow


def test_zoom_in_is_capped_at_max_scale(qapp):

    window = MainWindow()
    map_view = window.map_view

    map_view.scale = map_view.MAX_SCALE

    map_view.zoom_in()

    assert map_view.scale == map_view.MAX_SCALE


def test_zoom_out_is_floored_at_min_scale(qapp):

    window = MainWindow()
    map_view = window.map_view

    map_view.scale = map_view.MIN_SCALE

    map_view.zoom_out()

    assert map_view.scale == map_view.MIN_SCALE


def test_purely_horizontal_wheel_scroll_does_not_zoom(qapp):

    # Found in review: wheelEvent only checked angleDelta().y() > 0 to
    # decide zoom-in, and zoomed OUT for everything else — including a
    # purely horizontal scroll (Shift+wheel, or a trackpad two-finger
    # horizontal swipe), which has delta_y == 0.
    window = MainWindow()
    map_view = window.map_view

    starting_scale = map_view.scale

    event = QWheelEvent(
        QPointF(10, 10), QPointF(10, 10),
        QPoint(120, 0), QPoint(120, 0),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False
    )

    map_view.wheelEvent(event)

    assert map_view.scale == starting_scale
