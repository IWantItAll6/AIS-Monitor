from services.geo import destination_point


# What happens to the prediction line of a vessel slower than the minimum
# speed — slow vessels' SOG/COG is mostly GPS noise (a moored boat
# "moving" at 0.2 kn in a random direction), so by default they get none.
SLOW_MODE_DRAW = "Draw"
SLOW_MODE_DIM = "Dim"
SLOW_MODE_HIDE = "Hide"

SLOW_MODES = (SLOW_MODE_DRAW, SLOW_MODE_DIM, SLOW_MODE_HIDE)

# Stations that don't move, so a "prediction" would only draw noise.
NO_PREDICTION_STATION_TYPES = ("base_station", "aton")

STYLE_NORMAL = "normal"
STYLE_DIM = "dim"


def prediction_line_style(vessel, min_speed_kn, slow_mode):
    """How to draw a vessel's prediction line: STYLE_NORMAL, STYLE_DIM, or
    None for no line at all (no position/SOG/COG, a fixed station, not
    moving, or below min_speed_kn with slow_mode set to hide)."""

    if vessel.station_type in NO_PREDICTION_STATION_TYPES:
        return None

    if vessel.lat is None or vessel.lon is None or vessel.sog is None or vessel.cog is None:
        return None

    # Zero-length regardless of mode — nothing to draw.
    if vessel.sog <= 0:
        return None

    if vessel.sog >= min_speed_kn:
        return STYLE_NORMAL

    if slow_mode == SLOW_MODE_DRAW:
        return STYLE_NORMAL

    if slow_mode == SLOW_MODE_DIM:
        return STYLE_DIM

    return None


def prediction_end_point(vessel, minutes):
    """Where the vessel will be in `minutes` at its current SOG/COG."""

    return destination_point(vessel.lat, vessel.lon, vessel.cog, vessel.sog * minutes / 60)
