import json
import os
from math import cos, radians, hypot

# Expanding search radius (degrees) tried until at least one coastline point
# is found nearby — most places resolve at the first, small radius; this
# only widens for the rare place genuinely far out (mid-ocean islands).
SEARCH_RADII_DEG = [0.5, 1, 2, 5, 10, 20]

# Returned when no coastline point turns up even at the widest search
# radius — effectively "not coastal by any reasonable threshold" rather
# than an unbounded scan of the whole world.
FAR_SENTINEL_NM = 9999.0


def _nearest_shore_distance_nm(lat, lon, coastline):

    for radius_deg in SEARCH_RADII_DEG:

        rings = coastline.rings_in_bounds(
            lon - radius_deg, lon + radius_deg, lat - radius_deg, lat + radius_deg
        )

        best = None

        for ring in rings:
            for point_lon, point_lat in ring["points"]:

                # Local flat-earth approximation (fine at these distances):
                # a degree of latitude is 60nm everywhere, a degree of
                # longitude is 60nm scaled by cos(latitude).
                d_lat_nm = (point_lat - lat) * 60
                d_lon_nm = (point_lon - lon) * 60 * cos(radians(lat))

                dist = hypot(d_lat_nm, d_lon_nm)

                if best is None or dist < best:
                    best = dist

        if best is not None:
            return best

    return FAR_SENTINEL_NM


def annotate_shore_distances(places, coastline, cache_path):

    # Nearest-coastline-vertex distance per place, cached to disk since
    # computing it involves scanning coastline geometry per place — a cost
    # worth paying once rather than on every app launch. Keyed by identity
    # (name + rounded position) rather than list order, so the cache still
    # matches correctly if the source dataset is re-ordered or partially
    # changed.
    cache = {}

    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    changed = False

    for place in places:

        key = f"{place['name']}|{place['lat']:.4f}|{place['lon']:.4f}"

        if key in cache:
            place["shore_distance_nm"] = cache[key]
            continue

        distance = _nearest_shore_distance_nm(place["lat"], place["lon"], coastline)

        place["shore_distance_nm"] = distance
        cache[key] = distance
        changed = True

    if changed:
        try:
            with open(cache_path, "w") as f:
                json.dump(cache, f)
        except Exception:
            pass

    return places
