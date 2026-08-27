from services.geo import calculate_range_bearing, convert_distance, format_distance


def test_same_point_is_zero_distance():

    distance, _ = calculate_range_bearing(50.0, -2.0, 50.0, -2.0)

    assert distance == 0


def test_known_distance_and_bearing_london_to_paris():

    distance, bearing = calculate_range_bearing(51.5074, -0.1278, 48.8566, 2.3522)

    assert 184 < distance < 187
    assert 147 < bearing < 149


def test_convert_distance_nm_is_passthrough():

    assert convert_distance(10, "NM") == 10


def test_convert_distance_miles_and_km():

    assert abs(convert_distance(10, "Miles") - 11.50779) < 0.001
    assert abs(convert_distance(10, "Km") - 18.52) < 0.001


def test_format_distance_uses_uppercase_nm_and_correct_suffixes():

    # NM (not lowercase nm) is the conventional marine abbreviation — nm on
    # its own is ambiguous with nanometres in SI units.
    assert format_distance(10, "NM") == "10.00 NM"
    assert format_distance(10, "Miles") == "11.51 mi"
    assert format_distance(10, "Km") == "18.52 km"
