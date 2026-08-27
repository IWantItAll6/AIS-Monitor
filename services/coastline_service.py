import json
import os

import shapefile

# Only rings spanning more than this get split at all — leaves the vast
# majority of rings (islands, individual coastline segments) untouched.
MIN_SPAN_TO_SPLIT = 30

# Granularity used once a ring is deemed worth splitting.
TILE_SIZE_DEGREES = 10


def _clip_against(points, inside, intersect):

    if not points:
        return []

    result = []
    prev = points[-1]
    prev_inside = inside(prev)

    for curr in points:

        curr_inside = inside(curr)

        if curr_inside:

            if not prev_inside:
                result.append(intersect(prev, curr))

            result.append(curr)

        elif prev_inside:
            result.append(intersect(prev, curr))

        prev, prev_inside = curr, curr_inside

    return result


def clip_polygon(points, min_lon, max_lon, min_lat, max_lat):

    intersect_lon = lambda a, b, x: (x, a[1] + (x - a[0]) / (b[0] - a[0]) * (b[1] - a[1]))
    intersect_lat = lambda a, b, y: (a[0] + (y - a[1]) / (b[1] - a[1]) * (b[0] - a[0]), y)

    pts = points
    pts = _clip_against(pts, lambda p: p[0] >= min_lon, lambda a, b: intersect_lon(a, b, min_lon))
    pts = _clip_against(pts, lambda p: p[0] <= max_lon, lambda a, b: intersect_lon(a, b, max_lon))
    pts = _clip_against(pts, lambda p: p[1] >= min_lat, lambda a, b: intersect_lat(a, b, min_lat))
    pts = _clip_against(pts, lambda p: p[1] <= max_lat, lambda a, b: intersect_lat(a, b, max_lat))

    return pts


class CoastlineService:

    def __init__(self, shapefile_path, tile_size=TILE_SIZE_DEGREES, min_span_to_split=MIN_SPAN_TO_SPLIT):

        self.shapefile_path = shapefile_path
        self.tile_size = tile_size
        self.min_span_to_split = min_span_to_split

        self.rings = []

        self.cache_path = f"{shapefile_path}.tiled_{min_span_to_split}_{tile_size}.cache.json"

    def load(self):

        if self._load_from_cache():
            return self.rings

        self.rings = []

        reader = shapefile.Reader(self.shapefile_path)

        for shape in reader.shapes():

            points = shape.points
            parts = list(shape.parts) + [len(points)]

            for i in range(len(parts) - 1):

                ring = points[parts[i]:parts[i + 1]]

                if len(ring) < 3:
                    continue

                self._add_tiled(ring)

        self._save_to_cache()

        return self.rings

    def _load_from_cache(self):

        if not os.path.exists(self.cache_path):
            return False

        if os.path.getmtime(self.cache_path) < os.path.getmtime(self.shapefile_path):
            return False

        try:
            with open(self.cache_path, "r") as f:
                self.rings = json.load(f)

            return True

        except Exception:
            return False

    def _save_to_cache(self):

        try:
            with open(self.cache_path, "w") as f:
                json.dump(self.rings, f)

        except Exception:
            pass

    def _add_ring(self, points):

        lons = [p[0] for p in points]
        lats = [p[1] for p in points]

        self.rings.append({
            "points": points,
            "min_lon": min(lons),
            "max_lon": max(lons),
            "min_lat": min(lats),
            "max_lat": max(lats)
        })

    def _add_tiled(self, ring):

        lons = [p[0] for p in ring]
        lats = [p[1] for p in ring]

        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)

        # Most rings (small islands, coastline segments) are already small —
        # only the handful of huge continental landmasses need splitting.
        if max(max_lon - min_lon, max_lat - min_lat) <= self.min_span_to_split:
            self._add_ring(ring)
            return

        tile = self.tile_size

        lon = int(min_lon // tile) * tile

        while lon < max_lon:

            lat = int(min_lat // tile) * tile

            while lat < max_lat:

                clipped = clip_polygon(ring, lon, lon + tile, lat, lat + tile)

                if len(clipped) >= 3:
                    self._add_ring(clipped)

                lat += tile

            lon += tile
