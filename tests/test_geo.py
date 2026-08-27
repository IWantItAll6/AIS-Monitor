from services.geo import calculate_range_bearing


def test_same_point_is_zero_distance():

    distance, _ = calculate_range_bearing(50.0, -2.0, 50.0, -2.0)

    assert distance == 0


def test_known_distance_and_bearing_london_to_paris():

    distance, bearing = calculate_range_bearing(51.5074, -0.1278, 48.8566, 2.3522)

    assert 184 < distance < 187
    assert 147 < bearing < 149
