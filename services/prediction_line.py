from services.geo import destination_point
from services.stationary import is_stationary


# Stations that don't move, so a "prediction" would only draw noise.
NO_PREDICTION_STATION_TYPES = ("base_station", "aton")

# SAR aircraft get a tenth of the ship prediction length: at aircraft
# speeds a 10-minute straight line runs ~20 NM, and a turning search
# pattern makes it swing wildly between 10s reports. A tenth (1 min at
# the default) stays short enough to still mean something mid-turn.
AIRCRAFT_PREDICTION_DIVISOR = 10


def has_prediction_line(vessel, stationary_speed_kn):
    """Whether a vessel gets a prediction line: it needs a position, SOG
    and COG, and must actually be moving — a stationary vessel's SOG/COG
    is mostly GPS noise (a moored boat "moving" at 0.2 kn in a random
    direction), so it gets none. Same stationary rule as the map's
    Dim/Hide setting (services/stationary.py)."""

    if vessel.station_type in NO_PREDICTION_STATION_TYPES:
        return False

    if vessel.lat is None or vessel.lon is None or vessel.sog is None or vessel.cog is None:
        return False

    return vessel.sog > 0 and not is_stationary(vessel, stationary_speed_kn)


def prediction_end_point(vessel, minutes):
    """Where the vessel will be in `minutes` (a tenth of that for SAR
    aircraft) at its current SOG/COG."""

    if vessel.station_type == "sar_aircraft":
        minutes /= AIRCRAFT_PREDICTION_DIVISOR

    return destination_point(vessel.lat, vessel.lon, vessel.cog, vessel.sog * minutes / 60)
