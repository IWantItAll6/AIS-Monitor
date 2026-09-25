import pytest

from models.vessel import Vessel
from services.geo import calculate_range_bearing, destination_point
from services.prediction_line import (
    prediction_line_style, prediction_end_point, STYLE_NORMAL, STYLE_DIM
)
from ui.main_window import MainWindow
from ui.preferences_dialog import PreferencesDialog


def make_vessel(sog=10.0, cog=90.0, station_type="vessel"):

    vessel = Vessel(mmsi=235000001, lat=50.5, lon=-2.3, sog=sog, cog=cog)
    vessel.station_type = station_type

    return vessel


@pytest.mark.parametrize("bearing,distance_nm", [(0, 1), (90, 10), (225, 40), (359, 0.2)])
def test_destination_point_is_the_inverse_of_range_bearing(bearing, distance_nm):

    lat, lon = destination_point(50.5, -2.3, bearing, distance_nm)

    back_distance, back_bearing = calculate_range_bearing(50.5, -2.3, lat, lon)

    assert back_distance == pytest.approx(distance_nm, rel=1e-6)
    assert back_bearing == pytest.approx(bearing, abs=1e-6)


def test_end_point_is_speed_times_time_along_course():

    # 12 kn for 10 min = 2 NM.
    lat, lon = prediction_end_point(make_vessel(sog=12, cog=45), 10)

    distance, bearing = calculate_range_bearing(50.5, -2.3, lat, lon)

    assert distance == pytest.approx(2)
    assert bearing == pytest.approx(45)


def test_moving_vessel_gets_a_normal_line():

    assert prediction_line_style(make_vessel(sog=10), 0.5, "Hide") == STYLE_NORMAL


@pytest.mark.parametrize("slow_mode,expected", [("Draw", STYLE_NORMAL), ("Dim", STYLE_DIM), ("Hide", None)])
def test_slow_vessel_follows_the_slow_mode(slow_mode, expected):

    assert prediction_line_style(make_vessel(sog=0.3), 0.5, slow_mode) == expected


def test_speed_exactly_at_the_minimum_counts_as_moving():

    assert prediction_line_style(make_vessel(sog=0.5), 0.5, "Hide") == STYLE_NORMAL


@pytest.mark.parametrize("sog,cog", [(None, 90), (10, None), (0, 90)])
def test_no_line_without_speed_and_course(sog, cog):

    # Zero speed has no length to draw, even when slow vessels are drawn.
    assert prediction_line_style(make_vessel(sog=sog, cog=cog), 0.5, "Draw") is None


@pytest.mark.parametrize("station_type", ["base_station", "aton"])
def test_fixed_stations_never_get_a_line(station_type):

    assert prediction_line_style(make_vessel(station_type=station_type), 0.5, "Draw") is None


def test_sar_aircraft_gets_a_line():

    assert prediction_line_style(make_vessel(sog=120, station_type="sar_aircraft"), 0.5, "Hide") == STYLE_NORMAL


def test_prediction_line_is_off_by_default(qapp):

    window = MainWindow()

    assert window.map_view.prediction_enabled is False


def test_preferences_prediction_settings_round_trip_and_apply(qapp, monkeypatch):

    window = MainWindow()

    dialog = PreferencesDialog(window.settings)

    # Dependent controls follow the checkbox.
    assert not dialog.prediction_line_minutes.isEnabled()

    dialog.prediction_line_enabled.setChecked(True)
    assert dialog.prediction_line_minutes.isEnabled()

    dialog.prediction_line_minutes.setValue(6)
    dialog.prediction_min_speed.setValue(2.0)
    dialog.prediction_slow_mode.setCurrentText("Dim")
    dialog.accept()

    assert window.settings["prediction_line_enabled"] is True
    assert window.settings["prediction_line_minutes"] == 6
    assert window.settings["prediction_min_speed_kn"] == 2.0
    assert window.settings["prediction_slow_mode"] == "Dim"

    dialog2 = PreferencesDialog(window.settings)
    assert dialog2.prediction_slow_mode.currentText() == "Dim"
    assert dialog2.prediction_min_speed.value() == 2.0

    window.apply_prediction_line_settings()

    map_view = window.map_view
    assert (map_view.prediction_enabled, map_view.prediction_minutes,
            map_view.prediction_min_speed_kn, map_view.prediction_slow_mode) == (True, 6, 2.0, "Dim")


def test_map_draws_prediction_lines_without_error(qapp):

    window = MainWindow()
    window.resize(800, 600)

    vessels = [make_vessel(sog=10), make_vessel(sog=0.2), make_vessel(sog=120, station_type="sar_aircraft")]
    for i, vessel in enumerate(vessels):
        vessel.mmsi += i

    window.map_view.set_prediction_line(True, 10, 0.5, "Dim")
    window.map_view.update_vessels(vessels, {"lat": None, "lon": None, "fix": False}, [])
    window.map_view.set_center(50.5, -2.3)

    window.map_view.grab()
