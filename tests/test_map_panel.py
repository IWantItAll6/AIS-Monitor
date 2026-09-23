from types import SimpleNamespace

import pytest
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


def test_fit_to_points_matches_fit_to_vessels_for_the_same_points(qapp):

    # fit_to_vessels() is a thin wrapper around fit_to_points() built from
    # self.vessels — the two must produce identical center/scale for an
    # equivalent point list.
    window = MainWindow()
    map_view = window.map_view

    map_view.vessels = [
        SimpleNamespace(lat=50.0, lon=-2.0),
        SimpleNamespace(lat=51.0, lon=-3.0),
    ]
    map_view.own_position = {"lat": None, "lon": None, "fix": False}

    map_view.fit_to_vessels()
    via_vessels = (map_view.center_lat, map_view.center_lon, map_view.scale)

    map_view.center_lat, map_view.center_lon, map_view.scale = 0.0, 0.0, map_view.DEFAULT_SCALE

    map_view.fit_to_points([(50.0, -2.0), (51.0, -3.0)])
    via_points = (map_view.center_lat, map_view.center_lon, map_view.scale)

    assert via_points == via_vessels


def test_set_static_track_fits_view_and_draws_without_error(qapp):

    window = MainWindow()
    map_view = window.map_view

    track = [
        (None, 50.0, -2.0),
        (None, 50.5, -2.5),
        (None, 51.0, -3.0),
    ]

    map_view.set_static_track(track)

    assert map_view.static_track == track
    assert map_view.center_lat == pytest.approx(50.5)

    # grab() forces a real paintEvent — draw_static_track must not raise
    # for a widget with no live vessels/coastline data assumptions broken.
    map_view.grab()

    map_view.clear_static_track()
    assert map_view.static_track is None


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
