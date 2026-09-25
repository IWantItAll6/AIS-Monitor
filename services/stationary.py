from services.ais_reporting_intervals import CLASS_A_ANCHORED_NAV_STATUSES, LOW_SPEED_THRESHOLD_KN


# What the map does with stationary vessels (Preferences > Map) — the
# stored setting values, in the order the Preferences combo lists them.
STATIONARY_SHOW = "Show"
STATIONARY_DIM = "Dim"
STATIONARY_HIDE = "Hide"

STATIONARY_MODES = (STATIONARY_SHOW, STATIONARY_DIM, STATIONARY_HIDE)

# Fixed stations — always stationary, whatever (if anything) they report
# for speed. Distress beacons are deliberately not here, nor anywhere the
# Dim/Hide setting reaches: they must always stand out.
FIXED_STATION_TYPES = ("aton", "base_station")


def is_stationary(vessel, speed_kn):
    """Whether a vessel is sitting still: SOG below speed_kn, or reporting
    At Anchor / Moored. Nav status alone isn't trusted when the vessel is
    plainly moving — crews often leave it stale — so it only counts when
    SOG is unknown or at most LOW_SPEED_THRESHOLD_KN (the same "low speed"
    the anchored reporting-interval rule uses)."""

    if vessel.sog is not None and vessel.sog < speed_kn:
        return True

    if vessel.nav_status in CLASS_A_ANCHORED_NAV_STATUSES:
        return vessel.sog is None or vessel.sog <= LOW_SPEED_THRESHOLD_KN

    return False


def can_attenuate(vessel, own_mmsi=None):
    """Whether the stationary Dim/Hide setting may apply to this station at
    all: ordinary ships and fixed stations (AtoNs, base stations). Pinned
    vessels (an explicit "keep following this one"), own ship, distress
    beacons and aircraft are always drawn normally."""

    return (
        vessel.station_type in ("vessel",) + FIXED_STATION_TYPES
        and not vessel.pinned and vessel.mmsi != own_mmsi
    )


def attenuated(vessel, speed_kn, own_mmsi=None):

    if not can_attenuate(vessel, own_mmsi):
        return False

    return vessel.station_type in FIXED_STATION_TYPES or is_stationary(vessel, speed_kn)
