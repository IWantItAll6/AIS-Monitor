from math import cos, sin, radians, log2, hypot

from PySide6.QtWidgets import QWidget, QPushButton
from PySide6.QtGui import QPainter, QColor, QPolygonF, QPen
from PySide6.QtCore import Qt, QPointF, QRect, QRectF, Signal

from services.coastline_service import CoastlineService
from services.places_service import PlacesService
from services.uk_towns_service import UkTownsService
from services.shore_distance_service import annotate_shore_distances, FAR_SENTINEL_NM as FAR_SHORE_DISTANCE_NM
from services.geo import (
    NM_PER_UNIT, UNIT_SUFFIX, mercator_y, inverse_mercator_y, nice_scale_value, MAX_MERCATOR_LATITUDE
)


class MapPanel(QWidget):

    vessel_clicked = Signal(int)
    vessel_double_clicked = Signal(int)

    DEFAULT_CENTER_LAT = 54.5
    DEFAULT_CENTER_LON = -3.0

    WATER_COLOR = QColor(20, 40, 60)
    LAND_COLOR = QColor(60, 90, 50)
    PLACE_COLOR = QColor(230, 220, 190)

    # Defaults for the user-configurable vessel/pinned colors below — not
    # used directly for drawing (self.vessel_color/self.pinned_color are).
    DEFAULT_VESSEL_COLOR = "#FF8C00"
    DEFAULT_PINNED_COLOR = "#FFD700"

    OWN_SHIP_COLOR = QColor(80, 200, 255)
    OWN_TRACK_COLOR = QColor(80, 200, 255, 210)
    SCALE_BAR_COLOR = QColor(255, 255, 255)

    # Pinned vessels get a ring around their marker in addition to their
    # own color — the default orange/gold pair sits close together for
    # red-green color vision deficiency, so the distinction shouldn't rely
    # on color alone (and a user could still pick two similar custom
    # colors via Preferences).
    PIN_RING_COLOR = QColor(255, 255, 255, 220)
    PIN_RING_RADIUS = 9

    # The scale bar's fixed on-screen length (a quarter of the map's width)
    # with tick marks subdividing it — its on-screen length never changes;
    # the E24 nice-number value labelling it is a rounded approximation of
    # that fixed length instead. See draw_scale_bar()/nice_scale_value().
    SCALE_BAR_WIDTH_FRACTION = 0.25
    SCALE_BAR_TICKS = 4

    # Caps how many town/city dots+labels render regardless of how many
    # technically qualify by zoom level — without this, a moderate zoom
    # covering a large area can make thousands of towns worldwide eligible
    # at once (population-based zoom thresholds don't know how many
    # candidates fall in the current viewport).
    MAX_VISIBLE_PLACES = 60

    # Bucket size for the lookup grid used to narrow the combined
    # places+towns list to roughly what's in view before the precise
    # per-frame filtering — avoids re-scanning every place worldwide on
    # every repaint while dragging/zooming.
    PLACE_GRID_SIZE_DEGREES = 10

    # Just the standard Web Mercator pole limit (see geo.MAX_MERCATOR_LATITUDE)
    # — under true Mercator, unlike the old equirectangular-with-cos(center_lat)
    # scheme this replaced, project()'s lon_scale no longer depends on
    # center_lat at all, so there's no sliver-squeeze reason to clamp any
    # tighter than where the projection itself stops being finite.
    MAX_ABS_LATITUDE = MAX_MERCATOR_LATITUDE

    # Below this, switch coastline rendering to CoastlineService's
    # simplified geometry — profiling showed the full 1:10m detail (~450K
    # points worldwide) takes a repaint from ~15ms to 150-300ms at wide
    # zoom, which is what made panning feel laggy at those scales. Derived
    # from the old threshold (0.5 old-pixels-per-nm) the same way as
    # DEFAULT_SCALE, as a starting point — a pure perf-tuning knob, not
    # user-visible behavior, so it's fine to retune after profiling.
    COARSE_RENDER_THRESHOLD_SCALE = 0.5 * cos(radians(DEFAULT_CENTER_LAT))

    # Ceiling on how far fit_to_vessels()/wheel-zoom can zoom in — without
    # this, a cluster of vessels at (near-)identical positions would drive
    # scale towards infinity. Just needs to comfortably exceed any real
    # zoom-to-fit case (a 0.01nm-wide cluster needs roughly 25,000).
    MAX_SCALE = 1_000_000

    # Floor for zoom_out()/wheel-zoom-out — without this, scale asymptotes
    # towards (but never quite reaches) zero, and everything downstream
    # that divides by it (pixels-per-nm, the scale bar) degrades towards
    # meaningless values long before that. The whole ~21,600nm world
    # circumference still spans a visible ~20px at this floor.
    MIN_SCALE = 0.001

    # Points north (up) before rotation — QPainter.rotate() is clockwise,
    # matching compass bearings, so rotating by heading/COG degrees directly
    # points the bow the right way.
    VESSEL_TRIANGLE = QPolygonF([QPointF(0, -6), QPointF(4, 5), QPointF(-4, 5)])

    # Non-vessel AIS station markers — shape-coded (not just color-coded) so
    # they stay distinguishable under color vision deficiency and read at a
    # glance as "not a ship": a square for a fixed base station, a diamond
    # for an Aid to Navigation (the IALA convention), and a cross-in-circle
    # distress mark shared by SART/MOB/EPIRB safety beacons.
    BASE_STATION_HALF_SIZE = 5
    ATON_HALF_SIZE = 6
    SAFETY_MARK_RADIUS = 6
    SAFETY_MARK_COLOR = QColor(255, 60, 60)

    # A vivid magenta for a pinned SART/MOB/EPIRB — distinct from both the
    # normal alarm red (always high-visibility) and the gold used for
    # pinned vessels, so a pinned safety mark still reads unambiguously as
    # "distress" while showing it's been pinned. (A pastel red was tried
    # first but read as washed-out/low-contrast against the map.)
    PINNED_SAFETY_MARK_COLOR = QColor(255, 0, 144)

    # Candidate label placements tried, in order, around each vessel marker
    # before giving up and suppressing the label (widest angle spread first
    # at the tightest radius, then step out to a wider radius).
    LABEL_RADII = (14, 20, 26)
    LABEL_ANGLE_OFFSETS = (0, 60, -60, 120, -120, 180)

    # Half-width/height of the square obstacle a vessel marker occupies —
    # labels must clear this even for vessels whose own label got suppressed.
    MARKER_HALF_SIZE = 7

    # `scale` means pixels per nautical mile AT THE EQUATOR — the single
    # Mercator zoom parameter (same for both axes; see project()). 0.75 is
    # the old default view's pixels-per-nm (accurate everywhere in the
    # previous equirectangular scheme), converted to the equator-referenced
    # value that reproduces the same on-screen zoom at DEFAULT_CENTER_LAT,
    # so the startup view looks the same as before.
    DEFAULT_SCALE = 0.75 * cos(radians(DEFAULT_CENTER_LAT))

    # Matches the per-notch factor wheelEvent already used, so the +/-
    # buttons feel like a single wheel notch rather than a bigger jump.
    ZOOM_FACTOR = 1.2

    ZOOM_BUTTON_SIZE = 36
    ZOOM_BUTTON_MARGIN = 12

    def __init__(self, coastline_path, places_path, uk_towns_path):
        super().__init__()

        self.coastline = CoastlineService(coastline_path)
        self.coastline.load()

        self.places = PlacesService(places_path)
        self.places.load()

        self.uk_towns = UkTownsService(uk_towns_path)
        self.uk_towns.load()

        annotate_shore_distances(self.places.places, self.coastline, f"{places_path}.shore_distance.cache.json")
        annotate_shore_distances(self.uk_towns.places, self.coastline, f"{uk_towns_path}.shore_distance.cache.json")

        self.show_place_names = True
        self.coastal_towns_only = False
        self.coastal_threshold_nm = 5.0

        self._build_places_index()

        self.center_lat = self.DEFAULT_CENTER_LAT
        self.center_lon = self.DEFAULT_CENTER_LON

        self.scale = self.DEFAULT_SCALE

        self.vessels = []
        self.own_position = {"lat": None, "lon": None, "fix": False}
        self.own_track = []
        self.distance_unit = "NM"
        self.scrub_animating = False
        self.empty_hint = False

        self.vessel_color = QColor(self.DEFAULT_VESSEL_COLOR)
        self.pinned_color = QColor(self.DEFAULT_PINNED_COLOR)

        # Last successful (radius, angle) per vessel MMSI — tried first each
        # frame before searching fresh, so a label's screen position stays
        # put across small pan/zoom changes instead of jumping between
        # equally-valid candidate slots every repaint.
        self.label_offsets = {}

        self._drag_start = None
        self._drag_last = None

        self.zoom_in_button = self._make_zoom_button("+")
        self.zoom_out_button = self._make_zoom_button("−")

        self.zoom_in_button.clicked.connect(self.zoom_in)
        self.zoom_out_button.clicked.connect(self.zoom_out)

    def _make_zoom_button(self, label):

        button = QPushButton(label, self)

        button.setFixedSize(self.ZOOM_BUTTON_SIZE, self.ZOOM_BUTTON_SIZE)

        # Overlaid directly on the map, so it needs its own contrast rather
        # than inheriting the app's theme palette (which assumes a normal
        # window background behind it, not variable terrain colors).
        button.setStyleSheet(
            "QPushButton {"
            "  background-color: rgba(0, 0, 0, 150);"
            "  color: white;"
            "  font-size: 18px;"
            "  font-weight: bold;"
            "  border: 1px solid rgba(255, 255, 255, 80);"
            "  border-radius: 6px;"
            "}"
            "QPushButton:hover { background-color: rgba(40, 40, 40, 180); }"
            "QPushButton:pressed { background-color: rgba(80, 80, 80, 200); }"
        )

        return button

    def _build_places_index(self):

        self._all_places = self.places.places + self.uk_towns.places

        self._places_grid = {}

        for place in self._all_places:

            key = (
                int(place["lon"] // self.PLACE_GRID_SIZE_DEGREES),
                int(place["lat"] // self.PLACE_GRID_SIZE_DEGREES)
            )

            self._places_grid.setdefault(key, []).append(place)

    def _places_in_bounds(self, min_lon, max_lon, min_lat, max_lat):

        result = []

        gx0 = int(min_lon // self.PLACE_GRID_SIZE_DEGREES)
        gx1 = int(max_lon // self.PLACE_GRID_SIZE_DEGREES)
        gy0 = int(min_lat // self.PLACE_GRID_SIZE_DEGREES)
        gy1 = int(max_lat // self.PLACE_GRID_SIZE_DEGREES)

        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                result.extend(self._places_grid.get((gx, gy), []))

        return result

    def set_show_place_names(self, show):

        self.show_place_names = show

        self.update()

    def set_coastal_filter(self, enabled, threshold_nm):

        self.coastal_towns_only = enabled
        self.coastal_threshold_nm = threshold_nm

        self.update()

    def _marker_color(self, vessel):

        # SART/MOB/EPIRB use their own fixed alarm-red/pinned-magenta pair
        # rather than the configurable vessel colors — computed here once
        # so every place a vessel's color is needed (marker, track) agrees,
        # rather than each place re-deriving it and risking drifting apart
        # (which is exactly how the original pinned-SART bug happened).
        if vessel.station_type in ("sart", "mob", "epirb"):
            return self.PINNED_SAFETY_MARK_COLOR if vessel.pinned else self.SAFETY_MARK_COLOR

        return self.pinned_color if vessel.pinned else self.vessel_color

    def resizeEvent(self, event):

        super().resizeEvent(event)

        x = self.width() - self.ZOOM_BUTTON_SIZE - self.ZOOM_BUTTON_MARGIN
        bottom = self.height() - self.ZOOM_BUTTON_SIZE - self.ZOOM_BUTTON_MARGIN

        self.zoom_out_button.move(x, bottom)
        self.zoom_in_button.move(x, bottom - self.ZOOM_BUTTON_SIZE - 4)

    def zoom_in(self):

        self.scale = min(self.scale * self.ZOOM_FACTOR, self.MAX_SCALE)

        self.update()

    def zoom_out(self):

        self.scale = max(self.scale / self.ZOOM_FACTOR, self.MIN_SCALE)

        self.update()

    def set_distance_unit(self, unit):

        self.distance_unit = unit

        self.update()

    def set_vessel_color(self, hex_color):

        self.vessel_color = QColor(hex_color)

        self.update()

    def set_pinned_color(self, hex_color):

        self.pinned_color = QColor(hex_color)

        self.update()

    def set_scrub_animating(self, animating):

        self.scrub_animating = animating

        self.update()

    def set_empty_hint(self, show):

        if show == self.empty_hint:
            return

        self.empty_hint = show

        self.update()

    def update_vessels(self, vessels, own_position, own_track):

        self.vessels = vessels
        self.own_track = own_track
        self.own_position = own_position

        self.update()

    def fit_to_vessels(self):

        positioned = [(v.lat, v.lon) for v in self.vessels if v.lat is not None and v.lon is not None]

        # Own ship counts as a target too — otherwise "zoom to fit" can
        # frame every other vessel while leaving your own position outside
        # the view, or centered on a spot that no longer includes it.
        own_lat, own_lon = self.own_position.get("lat"), self.own_position.get("lon")

        if self.own_position.get("fix") and own_lat is not None and own_lon is not None:
            positioned.append((own_lat, own_lon))

        if not positioned:
            return

        min_lat = min(lat for lat, _ in positioned)
        max_lat = max(lat for lat, _ in positioned)
        min_lon = min(lon for _, lon in positioned)
        max_lon = max(lon for _, lon in positioned)

        self.center_lat = max(-self.MAX_ABS_LATITUDE, min(self.MAX_ABS_LATITUDE, (min_lat + max_lat) / 2))
        self.center_lon = (min_lon + max_lon) / 2

        # 15% padding so targets aren't flush against the edge of the view.
        # The span floor here only guards against division by zero when
        # every vessel is at/near the exact same point — MAX_SCALE below is
        # what actually stops that case zooming in to infinity, so a
        # tight-but-real cluster (e.g. two vessels 0.01nm apart) can still
        # zoom in as far as that cluster genuinely warrants. Spans are in
        # Mercator-y/longitude nm-equivalent units (see project()), not raw
        # degrees, so scale comes out directly in pixels-per-equatorial-nm.
        y_span = max((mercator_y(max_lat) - mercator_y(min_lat)) * 1.15, 1e-6)
        x_span = max((max_lon - min_lon) * 60 * 1.15, 1e-6)

        scale_lat = self.height() / y_span
        scale_lon = self.width() / x_span

        self.scale = min(scale_lat, scale_lon, self.MAX_SCALE)

        self.update()

    def set_center(self, lat, lon):

        self.center_lat = max(-self.MAX_ABS_LATITUDE, min(self.MAX_ABS_LATITUDE, lat))
        self.center_lon = lon

        self.update()

    def project(self, lat, lon):

        # True (spherical) Web Mercator, in nm-equivalent units (1 degree
        # longitude = 60nm, matching the app's existing convention) so
        # `scale` means pixels per nautical mile at the equator. Unlike the
        # old equirectangular-with-cos(center_lat) approach, each point's
        # OWN latitude determines its scale here, not the current view
        # center — so nothing about a point's projection changes as you
        # pan, which is what made the map visibly thin/thicken before.
        x = self.width() / 2 + (lon * 60 - self.center_lon * 60) * self.scale
        y = self.height() / 2 - (mercator_y(lat) - mercator_y(self.center_lat)) * self.scale

        return QPointF(x, y)

    def current_zoom_level(self):

        # Expressed on the same 0-20ish scale as web map tile zoom levels
        # (360 degrees of longitude wrapping the world, 256px being the
        # standard web-map tile size) purely so the zoom-dependent place
        # thresholds in PlacesService/UkTownsService read like familiar map
        # zoom numbers — this app has no actual tiles. Converted through the
        # local pixels-per-degree-latitude at the current center so these
        # thresholds (tuned against the old, always-locally-accurate
        # formula) keep meaning the same thing under Mercator.
        local_pixels_per_degree = self.scale * 60 / cos(radians(self.center_lat))

        return log2(max(local_pixels_per_degree, 1e-6) * 360 / 256)

    def visible_bounds(self):

        # x and y are independent under Mercator, so each edge of the
        # viewport just needs its own inverse projection rather than a
        # symmetric half-span computed from the center.
        half_width_nm = (self.width() / 2) / self.scale
        min_lon = self.center_lon - half_width_nm / 60
        max_lon = self.center_lon + half_width_nm / 60

        half_height_nm = (self.height() / 2) / self.scale
        center_y = mercator_y(self.center_lat)
        max_lat = inverse_mercator_y(center_y + half_height_nm)
        min_lat = inverse_mercator_y(center_y - half_height_nm)

        return (min_lon, max_lon, min_lat, max_lat)

    def paintEvent(self, event):

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.fillRect(self.rect(), self.WATER_COLOR)

        # No border stroke: tile-split landmasses would show seams where
        # adjacent tiles meet if each drew its own outline.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.LAND_COLOR)

        cx, cy = self.width() / 2, self.height() / 2
        center_lon = self.center_lon
        center_merc_y = mercator_y(self.center_lat)

        # Cheap linear scale per point, same as before — the nonlinear
        # Mercator transform for each point's latitude is precomputed once
        # at load time (CoastlineService._add_ring's "merc_y") rather than
        # recomputed here on every repaint, so this hot loop's per-point
        # cost is unchanged from the pre-Mercator version.
        lon_scale = 60 * self.scale
        y_scale = self.scale

        min_lon, max_lon, min_lat, max_lat = self.visible_bounds()

        if self.scale < self.COARSE_RENDER_THRESHOLD_SCALE:
            visible_rings = self.coastline.coarse_rings_in_bounds(min_lon, max_lon, min_lat, max_lat)
        else:
            visible_rings = self.coastline.rings_in_bounds(min_lon, max_lon, min_lat, max_lat)

        for ring in visible_rings:

            if (
                ring["max_lon"] < min_lon or ring["min_lon"] > max_lon
                or ring["max_lat"] < min_lat or ring["min_lat"] > max_lat
            ):
                continue

            polygon = QPolygonF([
                QPointF(cx + (lon - center_lon) * lon_scale, cy - (merc_y - center_merc_y) * y_scale)
                for (lon, _), merc_y in zip(ring["points"], ring["merc_y"])
            ])

            painter.drawPolygon(polygon)

        self.draw_places(painter)
        self.draw_vessels(painter)
        self.draw_scale_bar(painter)

        if self.scrub_animating:
            self.draw_scrub_badge(painter)

        if self.empty_hint:
            self.draw_empty_hint(painter)

    def draw_empty_hint(self, painter):

        lines = [
            "No data loaded",
            "File → Open Replay or Load Sample Data",
            "or configure Communications and press Start",
        ]

        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)

        metrics = painter.fontMetrics()
        line_height = metrics.height()

        # Deliberately low-contrast — a hint for an empty map, not a modal
        # that should compete with anything drawn on top of it once data
        # starts arriving.
        painter.setPen(QColor(255, 255, 255, 110))

        top = self.height() / 2 - (len(lines) * line_height) / 2

        for i, line in enumerate(lines):

            text_width = metrics.horizontalAdvance(line)

            x = (self.width() - text_width) / 2
            y = top + i * line_height + metrics.ascent()

            painter.drawText(QPointF(x, y), line)

    def draw_scrub_badge(self, painter):

        text = "⏩ Catching up…"

        font = painter.font()
        font.setPointSize(18)
        font.setBold(True)
        painter.setFont(font)

        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(text)

        pad_x, pad_y = 20, 12
        badge_width = text_width + pad_x * 2
        badge_height = metrics.height() + pad_y * 2

        x0 = self.width() - badge_width - 12
        y0 = 12

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 150))
        painter.drawRoundedRect(QRect(int(x0), int(y0), int(badge_width), int(badge_height)), 10, 10)

        painter.setPen(QColor(255, 255, 255))
        painter.drawText(
            QPointF(x0 + pad_x, y0 + pad_y + metrics.ascent()),
            text
        )

    def draw_scale_bar(self, painter):

        # scale is pixels-per-nm AT THE EQUATOR; under Mercator the LOCAL
        # pixels-per-nm at the current view's latitude is scale/cos(lat) —
        # matching how real Mercator chart scale bars are stated as
        # accurate "at latitude X" rather than universally.
        pixels_per_nm = self.scale / cos(radians(self.center_lat))

        if pixels_per_nm <= 0:
            return

        pixels_per_unit = pixels_per_nm / NM_PER_UNIT.get(self.distance_unit, 1.0)

        # The bar itself is a fixed on-screen length (a quarter of the map's
        # width) — it never resizes with zoom or pan, only the map itself
        # does. Its exact raw value is instead rounded to the nearest E24
        # step for the label — see nice_scale_value().
        bar_px = self.width() * self.SCALE_BAR_WIDTH_FRACTION
        raw_value = bar_px / pixels_per_unit

        value, decimals = nice_scale_value(raw_value)

        if value <= 0:
            return

        x0 = 15
        y0 = self.height() - 15

        painter.setPen(QPen(self.SCALE_BAR_COLOR, 2))

        painter.drawLine(QPointF(x0, y0), QPointF(x0 + bar_px, y0))

        for i in range(self.SCALE_BAR_TICKS + 1):

            x = x0 + bar_px * i / self.SCALE_BAR_TICKS

            # Taller ticks at the two ends, shorter at the interior
            # subdivisions, so the bar reads like a ruler at a glance.
            tick_half_height = 5 if i in (0, self.SCALE_BAR_TICKS) else 3

            painter.drawLine(QPointF(x, y0 - tick_half_height), QPointF(x, y0 + tick_half_height))

        unit_suffix = UNIT_SUFFIX.get(self.distance_unit, self.distance_unit)

        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        painter.drawText(QPointF(x0, y0 - 10), f"{value:.{decimals}f} {unit_suffix}")

    def draw_places(self, painter):

        if not self.show_place_names:
            return

        zoom = self.current_zoom_level()

        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        metrics = painter.fontMetrics()

        painter.setPen(QPen(self.PLACE_COLOR, 1))
        painter.setBrush(self.PLACE_COLOR)

        min_lon, max_lon, min_lat, max_lat = self.visible_bounds()

        # Filter to the viewport BEFORE ranking — a global "min_zoom
        # eligible" cutoff can still mean thousands of towns worldwide once
        # zoomed in a moderate amount, most of them nowhere near what's on
        # screen. Only rank/cap among what's actually in view. The grid
        # lookup narrows the candidate pool before this precise check runs,
        # so this doesn't re-scan every place worldwide on every repaint.
        in_view = [
            place for place in self._places_in_bounds(min_lon, max_lon, min_lat, max_lat)
            if place["min_zoom"] <= zoom
            and min_lat <= place["lat"] <= max_lat
            and min_lon <= place["lon"] <= max_lon
            and (
                not self.coastal_towns_only
                or place.get("shore_distance_nm", FAR_SHORE_DISTANCE_NM) <= self.coastal_threshold_nm
            )
        ]

        # More prominent places (lower min_zoom) get first claim, both on
        # the cap below and on label space — a small town's dot/label never
        # bumps a city's.
        in_view.sort(key=lambda p: p["min_zoom"])

        candidates = in_view[:self.MAX_VISIBLE_PLACES]

        placed_label_rects = []

        for place in candidates:

            point = self.project(place["lat"], place["lon"])

            painter.drawEllipse(point, 2, 2)

            label_pos = point + QPointF(5, 4)

            label_rect = metrics.boundingRect(place["name"])
            label_rect.moveBottomLeft(label_pos.toPoint())

            if any(label_rect.intersects(r) for r in placed_label_rects):
                continue

            placed_label_rects.append(label_rect)

            painter.drawText(label_pos, place["name"])

    def draw_vessels(self, painter):

        metrics = painter.fontMetrics()

        visible = [v for v in self.vessels if v.lat is not None and v.lon is not None]

        for vessel in visible:

            track = vessel.track

            if len(track) >= 2:

                track_color = QColor(self._marker_color(vessel))
                track_color.setAlpha(210)
                painter.setPen(QPen(track_color, 2))

                polyline = QPolygonF([self.project(t_lat, t_lon) for _, t_lat, t_lon in track])

                painter.drawPolyline(polyline)

        # Closer vessels claim label space first — they're the ones actually
        # relevant to the operator, unlike distant AIS contacts.
        visible.sort(key=lambda v: v.range if v.range is not None else float("inf"))

        # Every marker's footprint is an obstacle for labels — including a
        # vessel whose own label ends up suppressed — so text never lands
        # on top of a ship symbol, not just on top of other text.
        placed_label_rects = []

        for vessel in visible:

            point = self.project(vessel.lat, vessel.lon)

            if self.rect().contains(point.toPoint()):
                r = self.MARKER_HALF_SIZE
                placed_label_rects.append(QRect(int(point.x() - r), int(point.y() - r), r * 2, r * 2))

        new_label_offsets = {}

        for vessel in visible:

            point = self.project(vessel.lat, vessel.lon)

            if not self.rect().contains(point.toPoint()):
                continue

            vessel_color = self._marker_color(vessel)

            # A ring around the marker, independent of fill color, so a
            # pinned vessel is still distinguishable from a normal one
            # under red-green color vision deficiency (where the default
            # orange/gold pair sit close together) regardless of what
            # colors are actually configured.
            if vessel.pinned:
                painter.setPen(QPen(self.PIN_RING_COLOR, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(point, self.PIN_RING_RADIUS, self.PIN_RING_RADIUS)

            # True heading is more accurate than course-over-ground for which
            # way the bow points, but not every vessel reports it — fall back
            # to COG, and to a plain dot if neither is available. Only
            # meaningful for actual vessels — base stations, AtoNs, and
            # safety beacons are stationary (or their "heading" is noise).
            heading = vessel.heading
            orientation = heading if heading is not None else vessel.cog

            if vessel.station_type == "base_station":
                painter.setPen(QPen(vessel_color, 1))
                painter.setBrush(vessel_color)
                half = self.BASE_STATION_HALF_SIZE
                painter.drawRect(QRectF(point.x() - half, point.y() - half, half * 2, half * 2))

            elif vessel.station_type == "aton":
                half = self.ATON_HALF_SIZE
                diamond = QPolygonF([
                    point + QPointF(0, -half), point + QPointF(half, 0),
                    point + QPointF(0, half), point + QPointF(-half, 0),
                ])

                # A virtual AtoN marks a position with no physical structure
                # there — drawn hollow so it reads differently from a real,
                # physical mark even at a glance.
                if vessel.virtual_aid:
                    painter.setPen(QPen(vessel_color, 2))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                else:
                    painter.setPen(QPen(vessel_color, 1))
                    painter.setBrush(vessel_color)

                painter.drawPolygon(diamond)

            elif vessel.station_type in ("sart", "mob", "epirb"):
                # A distress-alarm cross-in-circle, in a fixed high-visibility
                # color rather than the configurable vessel colors — these are
                # safety-critical and should stand out regardless of theme.
                # Pinning still shifts it to a distinct magenta (rather than
                # the gold used for pinned vessels) so it never stops reading
                # as a distress mark. vessel_color already carries this via
                # _marker_color(), same as every other marker type.
                painter.setPen(QPen(vessel_color, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                r = self.SAFETY_MARK_RADIUS
                painter.drawEllipse(point, r, r)
                painter.drawLine(point + QPointF(-r, 0), point + QPointF(r, 0))
                painter.drawLine(point + QPointF(0, -r), point + QPointF(0, r))

            else:
                painter.setPen(QPen(vessel_color, 1))
                painter.setBrush(vessel_color)

                if orientation is None:
                    painter.drawEllipse(point, 4, 4)

                else:
                    painter.save()
                    painter.translate(point)
                    painter.rotate(orientation)
                    painter.drawPolygon(self.VESSEL_TRIANGLE)
                    painter.restore()

            label_text = vessel.name or str(vessel.mmsi)

            # Preferred label direction is ahead of the vessel's travel —
            # a fixed offset sits directly on top of the trailing track for
            # any vessel heading roughly in that same fixed direction.
            preferred_angle = orientation if orientation is not None else 135

            # When the preferred spot is already taken, try nudging the
            # label around the marker (widening angle, then radius) instead
            # of just suppressing it — lets close-together vessels each
            # find a free slot. Only a genuinely packed cluster (more
            # candidates than slots) still falls back to suppression.
            # The vessel's last successful placement is tried first so its
            # label doesn't jump between equally-valid slots on every
            # repaint as the view pans/zooms.
            sticky = self.label_offsets.get(vessel.mmsi)
            candidates = ([sticky] if sticky is not None else []) + [
                (radius, preferred_angle + angle_offset)
                for radius in self.LABEL_RADII
                for angle_offset in self.LABEL_ANGLE_OFFSETS
            ]

            for radius, angle in candidates:

                dx = sin(radians(angle)) * radius
                dy = -cos(radians(angle)) * radius

                if dx < 0:
                    label_pos = point + QPointF(dx - metrics.horizontalAdvance(label_text), dy)

                else:
                    label_pos = point + QPointF(dx, dy)

                label_rect = metrics.boundingRect(label_text)
                label_rect.moveBottomLeft(label_pos.toPoint())

                if not any(label_rect.intersects(r) for r in placed_label_rects):
                    placed_label_rects.append(label_rect)
                    new_label_offsets[vessel.mmsi] = (radius, angle)
                    painter.drawText(label_pos, label_text)
                    break

        self.label_offsets = new_label_offsets

        if len(self.own_track) >= 2:

            painter.setPen(QPen(self.OWN_TRACK_COLOR, 2))

            polyline = QPolygonF([self.project(t_lat, t_lon) for _, t_lat, t_lon in self.own_track])

            painter.drawPolyline(polyline)

        own_lat, own_lon = self.own_position.get("lat"), self.own_position.get("lon")

        if self.own_position.get("fix") and own_lat is not None and own_lon is not None:

            point = self.project(own_lat, own_lon)

            painter.setPen(QPen(self.OWN_SHIP_COLOR, 2))
            painter.setBrush(self.OWN_SHIP_COLOR)

            own_cog = self.own_position.get("cog")

            if own_cog is None:
                painter.drawEllipse(point, 5, 5)

            else:
                painter.save()
                painter.translate(point)
                painter.rotate(own_cog)
                painter.drawPolygon(self.VESSEL_TRIANGLE)
                painter.restore()

    def wheelEvent(self, event):

        delta_y = event.angleDelta().y()

        # A purely horizontal scroll (Shift+wheel, or a trackpad two-finger
        # horizontal swipe) has delta_y == 0 — used to fall into the "else"
        # branch below and zoom out, so a horizontal gesture silently
        # zoomed instead of doing nothing.
        if delta_y > 0:
            self.zoom_in()

        elif delta_y < 0:
            self.zoom_out()

    def mousePressEvent(self, event):

        if event.button() == Qt.MouseButton.LeftButton:

            self._drag_start = event.position()
            self._drag_last = event.position()

    def mouseMoveEvent(self, event):

        if self._drag_start is None:
            return

        pos = event.position()
        delta = pos - self._drag_last
        self._drag_last = pos

        # Under Mercator, `scale` applies uniformly regardless of latitude
        # (unlike the old pixels_per_degree*cos(center_lat), which changed
        # as center_lat changed mid-drag and let the map visibly slip
        # relative to the cursor) — so panning is just a linear delta in
        # projected space, then converted back to lat/lon.
        self.center_lon -= delta.x() / (60 * self.scale)

        new_merc_y = mercator_y(self.center_lat) + delta.y() / self.scale
        new_lat = inverse_mercator_y(new_merc_y)
        self.center_lat = max(-self.MAX_ABS_LATITUDE, min(self.MAX_ABS_LATITUDE, new_lat))

        self.update()

    def mouseReleaseEvent(self, event):

        if self._drag_start is not None:

            moved = event.position() - self._drag_start

            # A small pixel threshold, not "moved by exactly 0" — a real
            # click's mouse-down and mouse-up rarely land on the exact same
            # pixel, and without slack every click would register as a
            # (zero-distance) pan instead.
            if abs(moved.x()) < 4 and abs(moved.y()) < 4:
                self.handle_click(event.position())

        self._drag_start = None

    def handle_click(self, pos):

        mmsi = self.find_nearest_vessel(pos)

        if mmsi is not None:
            self.vessel_clicked.emit(mmsi)

    def find_nearest_vessel(self, pos, hit_radius=10):

        closest_mmsi = None
        closest_dist = hit_radius

        for vessel in self.vessels:

            lat, lon = vessel.lat, vessel.lon

            if lat is None or lon is None:
                continue

            point = self.project(lat, lon)

            dist = hypot(point.x() - pos.x(), point.y() - pos.y())

            if dist < closest_dist:
                closest_dist = dist
                closest_mmsi = vessel.mmsi

        return closest_mmsi

    def mouseDoubleClickEvent(self, event):

        if event.button() != Qt.MouseButton.LeftButton:
            return

        mmsi = self.find_nearest_vessel(event.position())

        if mmsi is not None:
            self.vessel_double_clicked.emit(mmsi)
