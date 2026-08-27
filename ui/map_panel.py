from math import cos, sin, radians, log2, hypot

from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QPainter, QColor, QPolygonF, QPen
from PyQt6.QtCore import Qt, QPointF, pyqtSignal

from services.coastline_service import CoastlineService
from services.places_service import PlacesService
from services.uk_towns_service import UkTownsService


class MapPanel(QWidget):

    vessel_clicked = pyqtSignal(int)
    vessel_double_clicked = pyqtSignal(int)

    WATER_COLOR = QColor(20, 40, 60)
    LAND_COLOR = QColor(60, 90, 50)
    PLACE_COLOR = QColor(230, 220, 190)
    VESSEL_COLOR = QColor(255, 140, 0)
    TRACK_COLOR = QColor(255, 140, 0, 210)
    PINNED_VESSEL_COLOR = QColor(255, 215, 0)
    PINNED_TRACK_COLOR = QColor(255, 215, 0, 210)
    OWN_SHIP_COLOR = QColor(80, 200, 255)
    OWN_TRACK_COLOR = QColor(80, 200, 255, 210)
    SCALE_BAR_COLOR = QColor(255, 255, 255)

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

    DEFAULT_CENTER_LAT = 54.5
    DEFAULT_CENTER_LON = -3.0
    DEFAULT_PIXELS_PER_DEGREE = 45

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

        self._drag_start = None
        self._drag_origin = None

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

        view_size = 800

        scale_lat = view_size / lat_span
        scale_lon = view_size / (lon_span * cos(radians(self.center_lat)))

        self.pixels_per_degree = min(scale_lat, scale_lon)

    def set_center(self, lat, lon):

        self.center_lat = lat
        self.center_lon = lon

        self.update()

    def project(self, lat, lon):

        x = (
            self.width() / 2
            + (lon - self.center_lon) * self.pixels_per_degree * cos(radians(self.center_lat))
        )

        y = self.height() / 2 - (lat - self.center_lat) * self.pixels_per_degree

        return QPointF(x, y)

    def current_zoom_level(self):

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

    def draw_scale_bar(self, painter):

        # 1 degree of latitude is, by definition, 60 nautical miles — using
        # latitude rather than longitude for the scale avoids the cos(lat)
        # longitude compression, and keeps units consistent with the range
        # column elsewhere in the app (nm, not metric).
        pixels_per_nm = self.pixels_per_degree / 60

        if pixels_per_nm <= 0:
            return

        max_bar_px = 150

        nm = self.SCALE_STEPS_NM[0]

        for step in self.SCALE_STEPS_NM:

            if step * pixels_per_nm > max_bar_px:
                break

            nm = step

        bar_px = nm * pixels_per_nm

        x0 = 15
        y0 = self.height() - 15

        painter.setPen(QPen(self.SCALE_BAR_COLOR, 2))

        painter.drawLine(QPointF(x0, y0), QPointF(x0 + bar_px, y0))
        painter.drawLine(QPointF(x0, y0 - 4), QPointF(x0, y0 + 4))
        painter.drawLine(QPointF(x0 + bar_px, y0 - 4), QPointF(x0 + bar_px, y0 + 4))

        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        painter.drawText(QPointF(x0, y0 - 8), f"{nm:g} nm")

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

        visible = [v for v in self.vessels if v.get("lat") is not None and v.get("lon") is not None]

        for vessel in visible:

            track = vessel.get("track", [])

            if len(track) >= 2:

                track_color = self.PINNED_TRACK_COLOR if vessel.get("pinned") else self.TRACK_COLOR
                painter.setPen(QPen(track_color, 2))

                polyline = QPolygonF([self.project(t_lat, t_lon) for _, t_lat, t_lon in track])

                painter.drawPolyline(polyline)

        # Closer vessels claim label space first — they're the ones actually
        # relevant to the operator, unlike distant AIS contacts.
        visible.sort(key=lambda v: v.get("range", float("inf")))

        placed_label_rects = []

        for vessel in visible:

            point = self.project(vessel["lat"], vessel["lon"])

            if not self.rect().contains(point.toPoint()):
                continue

            vessel_color = self.PINNED_VESSEL_COLOR if vessel.get("pinned") else self.VESSEL_COLOR
            painter.setPen(QPen(vessel_color, 1))
            painter.setBrush(vessel_color)

            # True heading is more accurate than course-over-ground for which
            # way the bow points, but not every vessel reports it — fall back
            # to COG, and to a plain dot if neither is available.
            heading = vessel.get("heading")
            orientation = heading if heading is not None else vessel.get("cog")

            if orientation is None:
                painter.drawEllipse(point, 4, 4)

            else:
                painter.save()
                painter.translate(point)
                painter.rotate(orientation)
                painter.drawPolygon(self.VESSEL_TRIANGLE)
                painter.restore()

            label_text = vessel.get("name") or str(vessel["mmsi"])

            # Anchor the label ahead of the vessel (in its direction of
            # travel) rather than a fixed screen offset — a fixed offset
            # sits directly on top of the trailing track for any vessel
            # heading roughly in that same fixed direction (e.g. west).
            if orientation is None:
                dx, dy = 6, 4

            else:
                dx = sin(radians(orientation)) * 14
                dy = -cos(radians(orientation)) * 14

            if dx < 0:
                label_pos = point + QPointF(dx - metrics.horizontalAdvance(label_text), dy)

            else:
                label_pos = point + QPointF(dx, dy)

            label_rect = metrics.boundingRect(label_text)
            label_rect.moveBottomLeft(label_pos.toPoint())

            if any(label_rect.intersects(r) for r in placed_label_rects):
                continue

            placed_label_rects.append(label_rect)

            painter.drawText(label_pos, label_text)

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

        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2

        self.pixels_per_degree *= factor

        self.update()

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

            lat, lon = vessel.get("lat"), vessel.get("lon")

            if lat is None or lon is None:
                continue

            point = self.project(lat, lon)

            dist = hypot(point.x() - pos.x(), point.y() - pos.y())

            if dist < closest_dist:
                closest_dist = dist
                closest_mmsi = vessel["mmsi"]

        return closest_mmsi

    def mouseDoubleClickEvent(self, event):

        if event.button() != Qt.MouseButton.LeftButton:
            return

        mmsi = self.find_nearest_vessel(event.position())

        if mmsi is not None:
            self.vessel_double_clicked.emit(mmsi)
