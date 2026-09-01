from math import radians, sin, cos, sqrt, atan2, atan, exp, log, tan, degrees, pi, floor, log10

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


# Standard Web Mercator latitude limit — where the projection's y-coordinate
# would reach +-infinity at the poles, it's instead clipped here so the map
# stays square, matching every other Mercator-based map (Google/OSM/Leaflet).
# Without this, a latitude at or beyond +-90 — a corrupted NMEA sentence, a
# GPS glitch, or (for the coastline dataset) Antarctica's land polygon
# closing its ring exactly at -90 — would send mercator_y() to +-infinity or
# raise (log(0) is a math domain error), instead of just clamping visually.
MAX_MERCATOR_LATITUDE = 85.05112878


def mercator_y(lat_deg):

    # Spherical Web Mercator's y-coordinate, scaled so degrees of latitude
    # near the equator read as nautical miles (60nm/degree) — matching the
    # app's existing lat/lon-as-nm convention rather than an arbitrary
    # Earth-radius unit.
    lat_deg = max(-MAX_MERCATOR_LATITUDE, min(MAX_MERCATOR_LATITUDE, lat_deg))

    return 60 * degrees(log(tan(pi / 4 + radians(lat_deg) / 2)))


# IEC 60063 "E24" preferred numbers — the same series standard resistors and
# capacitors come in, reused here for the same underlying reason: evenly
# spacing steps in log-space (each ~10% bigger than the last) guarantees a
# single zoom click always lands on a different step. The guarantee needs
# margin, not just a rough match — MapPanel.ZOOM_FACTOR moves the raw value
# by a factor of 1.2 (a ratio of ln(1.2)=0.182 in log-space) each click, so
# every step's ratio must stay under that, with room to spare for E24's
# steps not being perfectly even (they're rounded to 2 significant figures).
# E24's worst-case adjacent ratio is 1.3->1.5 (~1.154, i.e. ln=0.144) — safely
# under 0.182. The coarser E12 series (12 steps/decade) was tried first and
# looked almost fine-grained enough (ln(10)/12=0.192, barely above 0.182),
# but empirically still repeated a label every ~20 clicks or so: its own
# worst gap (also 1.3->1.5, ~1.154 in the real, rounded-to-2-sig-fig values)
# happened to exceed the click ratio right at that point, so two consecutive
# clicks both rounded to the same "1.2" step (120nm in the original report).
E24_STEPS = (
    1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0,
    3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1, 10.0
)


def nice_scale_value(value):

    # Rounds to the nearest E24 step (by log-ratio distance, appropriate for
    # a geometric series) — for a scale bar of fixed pixel length, whose
    # label can only approximate the raw value it represents, not match it
    # exactly. Returns (value, decimals) — decimals is how many decimal
    # places are needed to show that value exactly (E24 steps have at most
    # one significant decimal digit, e.g. 3.3, so this is usually 0 or 1
    # more than that, depending on the decade).
    if value <= 0:
        return 0, 0

    exponent = floor(log10(value))
    fraction = value / (10 ** exponent)

    nice_fraction = min(E24_STEPS, key=lambda step: abs(log10(fraction) - log10(step)))

    if nice_fraction == 10.0:
        nice_fraction, exponent = 1.0, exponent + 1

    result = nice_fraction * (10 ** exponent)

    frac_digits = 0 if nice_fraction == int(nice_fraction) else 1
    decimals = max(0, frac_digits - exponent)

    return result, decimals


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
