import json
import os
from math import hypot

import shapefile

# Only rings spanning more than this get split at all — leaves the vast
# majority of rings (islands, individual coastline segments) untouched.
MIN_SPAN_TO_SPLIT = 30

# Granularity used once a ring is deemed worth splitting.
TILE_SIZE_DEGREES = 10

# Bucket size for the lookup grid used by rings_in_bounds() — coarser than
# the tiling above since this only needs to prune "obviously nowhere near
# the viewport" rings cheaply, not partition geometry.
GRID_SIZE_DEGREES = 20

# Simplification tolerance (degrees) for the coarse ring set used at wide
# zoom — see coarse_rings_in_bounds(). ~0.05deg (~3nm) keeps continental
# shapes recognizable while cutting the full 1:10m dataset's point count
# drastically; measured to take rendering at a world-scale view from
# ~300ms/frame down to something that actually tracks the mouse.
SIMPLIFY_TOLERANCE_DEG = 0.05


# Sutherland-Hodgman polygon clipping: clip_polygon() below runs this once
# per edge of an axis-aligned tile box, each time keeping only the portion
# of the ring on the "inside" side of that edge and cutting new vertices in
# at the boundary crossings.
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


def _perpendicular_distance(point, start, end):

    x0, y0 = point
    x1, y1 = start
    x2, y2 = end

    if (x1, y1) == (x2, y2):
        return hypot(x0 - x1, y0 - y1)

    num = abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1)
    den = hypot(y2 - y1, x2 - x1)

    return num / den


def simplify_ring(points, tolerance):

    # Ramer-Douglas-Peucker: keep the two endpoints, find the point
    # furthest from the line between them, and recurse on both halves only
    # if that point is further than tolerance away — points that lie
    # essentially on the straight line get dropped.
    if len(points) < 3:
        return points

    start, end = points[0], points[-1]

    max_dist = 0
    index = 0

    for i in range(1, len(points) - 1):

        dist = _perpendicular_distance(points[i], start, end)

        if dist > max_dist:
            index = i
            max_dist = dist

    if max_dist > tolerance:

        left = simplify_ring(points[:index + 1], tolerance)
        right = simplify_ring(points[index:], tolerance)

        return left[:-1] + right

    return [start, end]


def _build_bucket_grid(rings):

    grid = {}

    for ring in rings:

        gx0 = int(ring["min_lon"] // GRID_SIZE_DEGREES)
        gx1 = int(ring["max_lon"] // GRID_SIZE_DEGREES)
        gy0 = int(ring["min_lat"] // GRID_SIZE_DEGREES)
        gy1 = int(ring["max_lat"] // GRID_SIZE_DEGREES)

        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                grid.setdefault((gx, gy), []).append(ring)

    return grid


def _query_bucket_grid(grid, min_lon, max_lon, min_lat, max_lat):

    # A ring can be filed under more than one bucket (it's added to every
    # bucket its bounding box touches), so dedupe by identity rather than
    # returning duplicates to the caller.
    seen = set()
    result = []

    gx0 = int(min_lon // GRID_SIZE_DEGREES)
    gx1 = int(max_lon // GRID_SIZE_DEGREES)
    gy0 = int(min_lat // GRID_SIZE_DEGREES)
    gy1 = int(max_lat // GRID_SIZE_DEGREES)

    for gx in range(gx0, gx1 + 1):
        for gy in range(gy0, gy1 + 1):
            for ring in grid.get((gx, gy), []):
                if id(ring) not in seen:
                    seen.add(id(ring))
                    result.append(ring)

    return result


class CoastlineService:

    def __init__(self, shapefile_path, tile_size=TILE_SIZE_DEGREES, min_span_to_split=MIN_SPAN_TO_SPLIT):

        self.shapefile_path = shapefile_path
        self.tile_size = tile_size
        self.min_span_to_split = min_span_to_split

        self.rings = []
        self.coarse_rings = []
        self.grid = {}
        self.coarse_grid = {}

        # Parsing the full-resolution shapefile and re-tiling every large
        # landmass is slow enough to notice on every app launch — cache the
        # tiled result and only redo it when the shapefile itself changes.
        # tile_size/min_span_to_split are baked into the filename since a
        # cache built with different tiling parameters isn't valid for a
        # different combination of them.
        self.cache_path = f"{shapefile_path}.tiled_{min_span_to_split}_{tile_size}.cache.json"

        # Separately cached: a simplified copy of the same rings, used at
        # wide zoom where the full 1:10m detail is both invisible and (at
        # ~450K points worldwide) expensive to scan/draw every frame. Keyed
        # off the same tiling params plus the simplification tolerance.
        self.coarse_cache_path = (
            f"{shapefile_path}.tiled_{min_span_to_split}_{tile_size}"
            f".coarse_{SIMPLIFY_TOLERANCE_DEG}.cache.json"
        )

    def load(self):

        if not self._load_from_cache():

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

        if not self._load_coarse_from_cache():

            self.coarse_rings = [
                {**ring, "points": simplify_ring(ring["points"], SIMPLIFY_TOLERANCE_DEG)}
                for ring in self.rings
            ]

            self._save_coarse_to_cache()

        self._build_grid()

        return self.rings

    def _build_grid(self):

        # Rebuilt fresh every load (cache hit or not) — cheap in-memory
        # indexing over already-loaded rings, not worth persisting itself.
        self.grid = _build_bucket_grid(self.rings)
        self.coarse_grid = _build_bucket_grid(self.coarse_rings)

    def rings_in_bounds(self, min_lon, max_lon, min_lat, max_lat):
        return _query_bucket_grid(self.grid, min_lon, max_lon, min_lat, max_lat)

    def coarse_rings_in_bounds(self, min_lon, max_lon, min_lat, max_lat):
        return _query_bucket_grid(self.coarse_grid, min_lon, max_lon, min_lat, max_lat)

    def _load_from_cache(self):

        if not os.path.exists(self.cache_path):
            return False

        # A cache older than the source shapefile is stale (e.g. the data
        # file was replaced) — fall through to rebuilding it.
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

    def _load_coarse_from_cache(self):

        if not os.path.exists(self.coarse_cache_path):
            return False

        if os.path.getmtime(self.coarse_cache_path) < os.path.getmtime(self.cache_path):
            return False

        try:
            with open(self.coarse_cache_path, "r") as f:
                self.coarse_rings = json.load(f)

            return True

        except Exception:
            return False

    def _save_coarse_to_cache(self):

        try:
            with open(self.coarse_cache_path, "w") as f:
                json.dump(self.coarse_rings, f)

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

        # Snap the starting corner to the tile grid (rather than starting
        # exactly at the ring's bounding box) so tile edges land at the same
        # coordinates across different rings/shapefiles.
        lon = int(min_lon // tile) * tile

        while lon < max_lon:

            lat = int(min_lat // tile) * tile

            while lat < max_lat:

                clipped = clip_polygon(ring, lon, lon + tile, lat, lat + tile)

                if len(clipped) >= 3:
                    self._add_ring(clipped)

                lat += tile

            lon += tile
