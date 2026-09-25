import pytest

from models.vessel import Vessel
from services.stationary import is_stationary, can_attenuate, attenuated
from ui.main_window import MainWindow
from ui.preferences_dialog import PreferencesDialog


NO_FIX = {"lat": None, "lon": None, "fix": False}


def make_vessel(mmsi=235000001, sog=0.2, nav_status=None, station_type="vessel", pinned=False, lat=50.5, lon=-2.3):

    vessel = Vessel(mmsi=mmsi, lat=lat, lon=lon, sog=sog, cog=90.0)
    vessel.nav_status = nav_status
    vessel.station_type = station_type
    vessel.pinned = pinned

    return vessel


@pytest.mark.parametrize("sog,nav_status,expected", [
    (0.2, None, True),         # below the threshold
    (0.5, None, False),        # exactly at it counts as moving
    (8, None, False),
    (None, None, False),       # no speed, no status: nothing says it's stationary
    (None, "AtAnchor", True),
    (2, "Moored", True),
    (8, "Moored", False),      # stale Moored status on a vessel that's clearly under way
])
def test_is_stationary(sog, nav_status, expected):

    assert is_stationary(make_vessel(sog=sog, nav_status=nav_status), 0.5) is expected


@pytest.mark.parametrize("station_type", ["aton", "base_station", "sart", "sar_aircraft"])
def test_only_ships_are_attenuated(station_type):

    assert not can_attenuate(make_vessel(station_type=station_type))


def test_pinned_and_own_ship_are_never_attenuated():

    assert not attenuated(make_vessel(pinned=True), 0.5)
    assert not attenuated(make_vessel(mmsi=999), 0.5, own_mmsi=999)
    assert attenuated(make_vessel(), 0.5)


def make_map(qapp, mode):

    window = MainWindow()
    window.resize(800, 600)

    moving = make_vessel(mmsi=1, sog=10)
    stationary = make_vessel(mmsi=2, sog=0.1, lat=50.51)
    aton = make_vessel(mmsi=3, sog=None, station_type="aton", lat=50.52)

    map_view = window.map_view
    map_view.set_stationary_vessels(mode, 0.5)
    map_view.update_vessels([moving, stationary, aton], NO_FIX, [])
    map_view.set_center(50.51, -2.3)

    return window, map_view


def test_show_mode_keeps_everything(qapp):

    _, map_view = make_map(qapp, "Show")

    assert [v.mmsi for v in map_view.shown_vessels()] == [1, 2, 3]
    assert not any(map_view._is_dimmed(v) for v in map_view.vessels)


def test_dim_mode_dims_only_the_stationary_ship(qapp):

    _, map_view = make_map(qapp, "Dim")

    assert [v.mmsi for v in map_view.shown_vessels()] == [1, 2, 3]
    assert [v.mmsi for v in map_view.vessels if map_view._is_dimmed(v)] == [2]

    map_view.grab()


def test_hide_mode_hides_from_drawing_and_clicks(qapp):

    _, map_view = make_map(qapp, "Hide")

    assert [v.mmsi for v in map_view.shown_vessels()] == [1, 3]

    stationary_point = map_view.project(50.51, -2.3)
    assert map_view.find_nearest_vessel(stationary_point) != 2

    map_view.grab()


def test_default_is_show(qapp):

    window = MainWindow()

    assert window.map_view.stationary_mode == "Show"
    assert window.map_view.stationary_speed_kn == 0.5


def test_preferences_stationary_settings_round_trip_and_apply(qapp):

    window = MainWindow()

    dialog = PreferencesDialog(window.settings)
    dialog.stationary_mode.setCurrentText("Dim")
    dialog.stationary_speed.setValue(2.0)
    dialog.accept()

    assert window.settings["stationary_mode"] == "Dim"
    assert window.settings["stationary_speed_kn"] == 2.0

    dialog2 = PreferencesDialog(window.settings)
    assert dialog2.stationary_mode.currentText() == "Dim"
    assert dialog2.stationary_speed.value() == 2.0

    window.apply_map_vessel_display_settings()

    assert (window.map_view.stationary_mode, window.map_view.stationary_speed_kn) == ("Dim", 2.0)
