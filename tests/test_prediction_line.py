import pytest

from models.vessel import Vessel
from services.geo import calculate_range_bearing, destination_point
from services.prediction_line import has_prediction_line, prediction_end_point
from ui.main_window import MainWindow
from ui.preferences_dialog import PreferencesDialog


def make_vessel(sog=10.0, cog=90.0, station_type="vessel", nav_status=None):

    vessel = Vessel(mmsi=235000001, lat=50.5, lon=-2.3, sog=sog, cog=cog)
    vessel.station_type = station_type
    vessel.nav_status = nav_status

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


def test_moving_vessel_gets_a_line():

    assert has_prediction_line(make_vessel(sog=10), 0.5)


def test_stationary_vessel_gets_no_line():

    assert not has_prediction_line(make_vessel(sog=0.3), 0.5)
    assert not has_prediction_line(make_vessel(sog=0.2, nav_status="Moored"), 0.5)


def test_speed_exactly_at_the_threshold_counts_as_moving():

    assert has_prediction_line(make_vessel(sog=0.5), 0.5)


@pytest.mark.parametrize("sog,cog", [(None, 90), (10, None), (0, 90)])
def test_no_line_without_speed_and_course(sog, cog):

    # Zero speed has no length to draw, even with the threshold at 0.
    assert not has_prediction_line(make_vessel(sog=sog, cog=cog), 0)


@pytest.mark.parametrize("station_type", ["base_station", "aton"])
def test_fixed_stations_never_get_a_line(station_type):

    assert not has_prediction_line(make_vessel(station_type=station_type), 0)


def test_sar_aircraft_line_is_a_tenth_of_the_ship_length():

    # 120 kn: 10 min would be 20 NM; a tenth of that is 2 NM.
    aircraft = make_vessel(sog=120, cog=90, station_type="sar_aircraft")

    lat, lon = prediction_end_point(aircraft, 10)

    distance, _ = calculate_range_bearing(50.5, -2.3, lat, lon)

    assert distance == pytest.approx(2)


def test_sar_aircraft_gets_a_line():

    assert has_prediction_line(make_vessel(sog=120, station_type="sar_aircraft"), 0.5)


def test_prediction_line_is_off_by_default(qapp):

    window = MainWindow()

    assert window.map_view.prediction_enabled is False


def test_preferences_prediction_settings_round_trip_and_apply(qapp):

    window = MainWindow()

    dialog = PreferencesDialog(window.settings)

    # The length follows the checkbox.
    assert not dialog.prediction_line_minutes.isEnabled()

    dialog.prediction_line_enabled.setChecked(True)
    assert dialog.prediction_line_minutes.isEnabled()

    dialog.prediction_line_minutes.setValue(6)
    dialog.accept()

    assert window.settings["prediction_line_enabled"] is True
    assert window.settings["prediction_line_minutes"] == 6

    window.apply_map_vessel_display_settings()

    assert (window.map_view.prediction_enabled, window.map_view.prediction_minutes) == (True, 6)


def test_map_draws_prediction_lines_without_error(qapp):

    window = MainWindow()
    window.resize(800, 600)

    vessels = [make_vessel(sog=10), make_vessel(sog=0.2), make_vessel(sog=120, station_type="sar_aircraft")]
    for i, vessel in enumerate(vessels):
        vessel.mmsi += i

    window.map_view.set_prediction_line(True, 10)
    window.map_view.update_vessels(vessels, {"lat": None, "lon": None, "fix": False}, [])
    window.map_view.set_center(50.5, -2.3)

    window.map_view.grab()
