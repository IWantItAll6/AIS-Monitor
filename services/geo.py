from math import radians, sin, cos, sqrt, atan2, degrees

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


def calculate_range_bearing(lat1, lon1, lat2, lon2):

    r = 6371000

    lat1r = radians(lat1)
    lon1r = radians(lon1)

    lat2r = radians(lat2)
    lon2r = radians(lon2)

    dlat = lat2r - lat1r
    dlon = lon2r - lon1r

    a = sin(dlat / 2) ** 2 + cos(lat1r) * cos(lat2r) * sin(dlon / 2) ** 2

    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    distance_m = r * c
    distance_nm = distance_m / 1852

    y = sin(dlon) * cos(lat2r)
    x = cos(lat1r) * sin(lat2r) - sin(lat1r) * cos(lat2r) * cos(dlon)

    bearing = (degrees(atan2(y, x)) + 360) % 360

    return distance_nm, bearing
