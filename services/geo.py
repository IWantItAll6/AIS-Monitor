from math import radians, sin, cos, sqrt, atan2, atan, exp, log, tan, degrees, pi

NM_PER_UNIT = {
    "NM": 1.0,
    "Miles": 1.150779,
    "Km": 1.852
}

UNIT_SUFFIX = {
    "NM": "NM",
    "Miles": "mi",
    "Km": "km"
}


def convert_distance(distance_nm, unit):

    return distance_nm * NM_PER_UNIT.get(unit, 1.0)


def format_distance(distance_nm, unit):

    return f"{convert_distance(distance_nm, unit):.2f} {UNIT_SUFFIX.get(unit, unit)}"


def mercator_y(lat_deg):

    # Spherical Web Mercator's y-coordinate, scaled so degrees of latitude
    # near the equator read as nautical miles (60nm/degree) — matching the
    # app's existing lat/lon-as-nm convention rather than an arbitrary
    # Earth-radius unit. Diverges as lat_deg approaches +-90; callers are
    # expected to keep latitude within a sane navigable range (this app
    # clamps to +-75, see MapPanel.MAX_ABS_LATITUDE).
    return 60 * degrees(log(tan(pi / 4 + radians(lat_deg) / 2)))


def inverse_mercator_y(y):

    return degrees(2 * atan(exp(radians(y / 60))) - pi / 2)


def calculate_range_bearing(lat1, lon1, lat2, lon2):

    # Mean Earth radius in meters — good enough for the distances/precision
    # this app deals with; not worth the complexity of an ellipsoidal model.
    r = 6371000

    lat1r = radians(lat1)
    lon1r = radians(lon1)

    lat2r = radians(lat2)
    lon2r = radians(lon2)

    dlat = lat2r - lat1r
    dlon = lon2r - lon1r

    # Haversine great-circle distance.
    a = sin(dlat / 2) ** 2 + cos(lat1r) * cos(lat2r) * sin(dlon / 2) ** 2

    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    distance_m = r * c
    distance_nm = distance_m / 1852

    # Initial (forward) bearing from point 1 to point 2 — not constant along
    # the great-circle path, but that's fine since this is only used for a
    # single range/bearing readout, not a route.
    y = sin(dlon) * cos(lat2r)
    x = cos(lat1r) * sin(lat2r) - sin(lat1r) * cos(lat2r) * cos(dlon)

    bearing = (degrees(atan2(y, x)) + 360) % 360

    return distance_nm, bearing
