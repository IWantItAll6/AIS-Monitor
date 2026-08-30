from math import cos, sin, radians, log2, hypot

from PySide6.QtWidgets import QWidget, QPushButton
from PySide6.QtGui import QPainter, QColor, QPolygonF, QPen
from PySide6.QtCore import Qt, QPointF, QRect, QRectF, Signal

from services.coastline_service import CoastlineService
from services.places_service import PlacesService
from services.uk_towns_service import UkTownsService
from services.geo import NM_PER_UNIT, UNIT_SUFFIX


class MapPanel(QWidget):

    vessel_clicked = Signal(int)
    vessel_double_clicked = Signal(int)

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

    SCALE_STEPS_NM = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000]

    # Caps how many town/city dots+labels render regardless of how many
    # technically qualify by zoom level — without this, a moderate zoom
    # covering a large area can make thousands of towns worldwide eligible
    # at once (population-based zoom thresholds don't know how many
    # candidates fall in the current viewport).
    MAX_VISIBLE_PLACES = 60

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

    # Candidate label placements tried, in order, around each vessel marker
    # before giving up and suppressing the label (widest angle spread first
    # at the tightest radius, then step out to a wider radius).
    LABEL_RADII = (14, 20, 26)
    LABEL_ANGLE_OFFSETS = (0, 60, -60, 120, -120, 180)

    # Half-width/height of the square obstacle a vessel marker occupies —
    # labels must clear this even for vessels whose own label got suppressed.
    MARKER_HALF_SIZE = 7

    DEFAULT_CENTER_LAT = 54.5
    DEFAULT_CENTER_LON = -3.0
    DEFAULT_PIXELS_PER_DEGREE = 45

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

        self.center_lat = self.DEFAULT_CENTER_LAT
        self.center_lon = self.DEFAULT_CENTER_LON

        self.pixels_per_degree = self.DEFAULT_PIXELS_PER_DEGREE

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
        self._drag_origin = None

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

    def resizeEvent(self, event):

        super().resizeEvent(event)

        x = self.width() - self.ZOOM_BUTTON_SIZE - self.ZOOM_BUTTON_MARGIN
        bottom = self.height() - self.ZOOM_BUTTON_SIZE - self.ZOOM_BUTTON_MARGIN

        self.zoom_out_button.move(x, bottom)
        self.zoom_in_button.move(x, bottom - self.ZOOM_BUTTON_SIZE - 4)

    def zoom_in(self):

        self.pixels_per_degree *= self.ZOOM_FACTOR

        self.update()

    def zoom_out(self):

        self.pixels_per_degree /= self.ZOOM_FACTOR

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

    def fit_to_extent(self):

        rings = self.coastline.rings

        if not rings:
            return

        min_lat = min(r["min_lat"] for r in rings)
        max_lat = max(r["max_lat"] for r in rings)
        min_lon = min(r["min_lon"] for r in rings)
        max_lon = max(r["max_lon"] for r in rings)

        self.center_lat = (min_lat + max_lat) / 2
        self.center_lon = (min_lon + max_lon) / 2

        lat_span = max(max_lat - min_lat, 1)
        lon_span = max(max_lon - min_lon, 1)

        # An assumed viewport size rather than the widget's actual current
        # size — this runs once at startup before the window has necessarily
        # settled into its final geometry. Only the ratio between the lat
        # and lon scales below matters, not this value's absolute size.
        view_size = 800

        scale_lat = view_size / lat_span
        scale_lon = view_size / (lon_span * cos(radians(self.center_lat)))

        # Whichever axis is more constraining wins, so the full extent fits
        # without cropping either dimension.
        self.pixels_per_degree = min(scale_lat, scale_lon)

    def set_center(self, lat, lon):

        self.center_lat = lat
        self.center_lon = lon

        self.update()

    def project(self, lat, lon):

        # Equirectangular projection, scaled by cos(center latitude) so a
        # degree of longitude shrinks to its correct on-screen width as you
        # move away from the equator. It's only locally accurate around
        # center_lat, not a true Mercator — fine for this app's zoom ranges,
        # not for wide-area or near-polar viewing.
        x = (
            self.width() / 2
            + (lon - self.center_lon) * self.pixels_per_degree * cos(radians(self.center_lat))
        )

        y = self.height() / 2 - (lat - self.center_lat) * self.pixels_per_degree

        return QPointF(x, y)

    def current_zoom_level(self):

        # Expressed on the same 0-20ish scale as web map tile zoom levels
        # (360 degrees of longitude wrapping the world, 256px being the
        # standard web-map tile size) purely so the zoom-dependent place
        # thresholds in PlacesService/UkTownsService read like familiar map
        # zoom numbers — this app has no actual tiles.
        return log2(max(self.pixels_per_degree, 1e-6) * 360 / 256)

    def visible_bounds(self):

        half_lon = (self.width() / 2) / (self.pixels_per_degree * cos(radians(self.center_lat)))
        half_lat = (self.height() / 2) / self.pixels_per_degree

        return (
            self.center_lon - half_lon,
            self.center_lon + half_lon,
            self.center_lat - half_lat,
            self.center_lat + half_lat
        )

    def paintEvent(self, event):

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.fillRect(self.rect(), self.WATER_COLOR)

        # No border stroke: tile-split landmasses would show seams where
        # adjacent tiles meet if each drew its own outline.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.LAND_COLOR)

        cx, cy = self.width() / 2, self.height() / 2
        center_lat, center_lon = self.center_lat, self.center_lon
        lon_scale = self.pixels_per_degree * cos(radians(center_lat))
        lat_scale = self.pixels_per_degree

        min_lon, max_lon, min_lat, max_lat = self.visible_bounds()

        for ring in self.coastline.rings:

            if (
                ring["max_lon"] < min_lon or ring["min_lon"] > max_lon
                or ring["max_lat"] < min_lat or ring["min_lat"] > max_lat
            ):
                continue

            polygon = QPolygonF([
                QPointF(cx + (lon - center_lon) * lon_scale, cy - (lat - center_lat) * lat_scale)
                for lon, lat in ring["points"]
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
        font.setPointSize(11)
        painter.setFont(font)

        metrics = painter.fontMetrics()
        line_height = metrics.height()

        painter.setPen(QColor(255, 255, 255, 200))

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

        # 1 degree of latitude is, by definition, 60 nautical miles — using
        # latitude rather than longitude for the scale avoids the cos(lat)
        # longitude compression.
        pixels_per_nm = self.pixels_per_degree / 60

        if pixels_per_nm <= 0:
            return

        pixels_per_unit = pixels_per_nm / NM_PER_UNIT.get(self.distance_unit, 1.0)

        max_bar_px = 150

        value = self.SCALE_STEPS_NM[0]

        for step in self.SCALE_STEPS_NM:

            if step * pixels_per_unit > max_bar_px:
                break

            value = step

        bar_px = value * pixels_per_unit

        x0 = 15
        y0 = self.height() - 15

        painter.setPen(QPen(self.SCALE_BAR_COLOR, 2))

        painter.drawLine(QPointF(x0, y0), QPointF(x0 + bar_px, y0))
        painter.drawLine(QPointF(x0, y0 - 4), QPointF(x0, y0 + 4))
        painter.drawLine(QPointF(x0 + bar_px, y0 - 4), QPointF(x0 + bar_px, y0 + 4))

        unit_suffix = UNIT_SUFFIX.get(self.distance_unit, self.distance_unit)

        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        painter.drawText(QPointF(x0, y0 - 8), f"{value:g} {unit_suffix}")

    def draw_places(self, painter):

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
        # screen. Only rank/cap among what's actually in view.
        in_view = [
            place for place in self.places.places + self.uk_towns.places
            if place["min_zoom"] <= zoom
            and min_lat <= place["lat"] <= max_lat
            and min_lon <= place["lon"] <= max_lon
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

                track_color = QColor(self.pinned_color if vessel.pinned else self.vessel_color)
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

            vessel_color = self.pinned_color if vessel.pinned else self.vessel_color

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
                painter.setPen(QPen(self.SAFETY_MARK_COLOR, 2))
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

        if event.angleDelta().y() > 0:
            self.zoom_in()

        else:
            self.zoom_out()

    def mousePressEvent(self, event):

        if event.button() == Qt.MouseButton.LeftButton:

            self._drag_start = event.position()
            self._drag_origin = (self.center_lat, self.center_lon)

    def mouseMoveEvent(self, event):

        if self._drag_start is None:
            return

        delta = event.position() - self._drag_start

        lat0, lon0 = self._drag_origin

        self.center_lon = lon0 - delta.x() / (self.pixels_per_degree * cos(radians(lat0)))
        self.center_lat = lat0 + delta.y() / self.pixels_per_degree

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
