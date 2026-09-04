from types import SimpleNamespace

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


def test_fit_to_vessels_is_floored_at_min_scale(qapp):

    # Found in review: fit_to_vessels() only clamped against MAX_SCALE, so
    # a zero-width map panel (e.g. its QSplitter dragged collapsed) made
    # scale_lon = width()/x_span come out as 0.0, silently setting
    # self.scale to 0 — everything downstream that divides by it
    # (visible_bounds(), the scale bar) would then crash the next paint.
    window = MainWindow()
    map_view = window.map_view

    map_view.resize(0, 400)
    map_view.vessels = [SimpleNamespace(lat=50.0, lon=-2.0)]
    map_view.own_position = {"lat": None, "lon": None, "fix": False}

    map_view.fit_to_vessels()

    assert map_view.scale == map_view.MIN_SCALE


def test_pan_wraps_center_lon_instead_of_drifting_unbounded(qapp):

    # Found in review: center_lat is clamped to +-MAX_ABS_LATITUDE right
    # after this same update, but center_lon had no equivalent wraparound —
    # at low scale (zoomed far out), a single drag could shift it by
    # thousands of degrees, after which every bounds check elsewhere
    # (coastline/place lookups, visible_bounds()) assumes a -180..180 range
    # and stops matching anything.
    window = MainWindow()
    map_view = window.map_view

    map_view.scale = map_view.MIN_SCALE
    map_view.center_lon = 170.0
    map_view._drag_start = QPointF(0, 0)
    map_view._drag_last = QPointF(0, 0)

    map_view.mouseMoveEvent(SimpleNamespace(position=lambda: QPointF(100, 0)))

    assert -180 <= map_view.center_lon < 180
