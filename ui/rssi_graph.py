from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtGui import QPainter, QColor, QPen, QPalette, QPolygonF
from PySide6.QtCore import Qt, QPointF, QRectF, Signal

from ui.time_format import format_age

# Candidate shapes for MARKER_SHAPES below — kept as a plain tuple (not an
# enum) since these are only ever driven by the experimental Test menu
# (see MainWindow.setup_test_menu), not stored settings.
MARKER_SHAPES = ("circle", "square", "diamond", "cross")


class RssiGraphWidget(QWidget):
    """Small hand-drawn sparkline of a vessel's RSSI over time — kept as a
    plain QPainter widget rather than pulling in a charting dependency, to
    match how MapPanel already hand-rolls its own rendering."""

    # Emitted on a scroll-wheel event over the graph — +1 to zoom in
    # (shorter window), -1 to zoom out (longer window, up to the track
    # length setting). MainWindow owns the actual zoom level (shared with
    # VesselUptimeBar, since the two are meant to be read together — see
    # MainWindow.adjust_graph_zoom); this widget only reports the gesture.
    zoom_requested = Signal(int)

    HEIGHT = 84
    MARGIN = 6

    # Reserved vertical space for the text rows (scale_max/caption at top,
    # scale_min at bottom) that the line itself must never enter — without
    # this, the line's plotting range spanned the *entire* widget height,
    # the same space the text occupies, so a value near the top or bottom
    # of the scale drew the line directly through/over the text (found on
    # a real multi-hour log where a vessel's RSSI swung close to the scale
    # edges — MMSI 970000014, ~11:21). Sized for the 8pt caption font used
    # below: enough clearance above the top baseline (ascent) and below/
    # above the bottom baseline for its full glyph height, plus a couple
    # px of breathing room.
    TOP_TEXT_PADDING = 13
    BOTTOM_TEXT_PADDING = 12

    # A dedicated row below the scale_min label for the time-axis labels
    # (oldest-sample age on the left, "now" on the right) — without this,
    # which side of the graph is the most recent data is only implicit
    # (newest on the right, matching a stock-chart/left-to-right-in-time
    # convention), which isn't obvious at a glance, especially having just
    # jumped to an arbitrary point in a long replay.
    TIME_AXIS_PADDING = 14

    # A round default scale for the RX analyser's RSSI readings (observed
    # in practice to sit roughly in this dBm range) rather than auto-scaling
    # tightly to whatever's currently visible, which would make a vessel's
    # signal look equally "noisy" whether it's actually fluctuating a lot or
    # a little. Expanded on the fly (see draw_graph) if real data ever falls
    # outside it, so nothing is ever clipped off-screen.
    DEFAULT_MIN_RSSI = -110
    DEFAULT_MAX_RSSI = -80

    # Below this, the last sample is close enough to "now" that spelling
    # out its age would just be noise (clock/processing jitter, not a
    # meaningfully stale reading).
    STALE_CAPTION_THRESHOLD = 3

    # A point only gets a per-gap marker (see marked_point_indices) if the
    # gap to at least one of its neighbors is at least this wide on screen
    # — evaluated per-gap rather than as one average across the whole line,
    # so a vessel whose rate varies (mostly fast, one real gap) still gets
    # a marker exactly where it's useful, and a uniformly fast vessel gets
    # none at all rather than a misleading average-based verdict.
    MIN_MARKER_GAP = 14
    MARKER_HALF_SIZE = 3

    def __init__(self, parent=None):

        super().__init__(parent)

        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.vessel_color = QColor("#FF8C00")
        self.pinned_color = QColor("#FFD700")

        self.history = []
        self.current_time = None
        self.pinned = False
        self.window_start = None

        # Experimental — driven only by the Test menu (see
        # MainWindow.setup_test_menu) while deciding how to indicate
        # individual transmissions without cluttering a fast-reporting
        # vessel's line. Not persisted; always off by default.
        self.show_point_markers = False
        self.show_endpoint_marker = False
        self.show_axis_ticks = False
        self.marker_shape = "circle"

    def set_vessel_color(self, hex_color):

        self.vessel_color = QColor(hex_color)

        self.update()

    def set_pinned_color(self, hex_color):

        self.pinned_color = QColor(hex_color)

        self.update()

    def set_marker_options(self, show_points, show_endpoint, show_axis_ticks, shape):
        """Experimental — see the Test menu. All three indicator modes are
        independent (any combination, including all three at once, is
        valid) so they can be visually compared side by side."""

        self.show_point_markers = show_points
        self.show_endpoint_marker = show_endpoint
        self.show_axis_ticks = show_axis_ticks
        self.marker_shape = shape

        self.update()

    def set_history(self, history, current_time, pinned=False, window_start=None):
        """window_start, when given, narrows the visible line to samples at
        or after it — independent of how much history is actually
        retained, so zooming in (see MainWindow.adjust_graph_zoom) doesn't
        discard anything, it just displays less of it. None (the default)
        shows the full retained history, same as before zoom existed."""

        # Copied rather than referencing the deque directly — the deque
        # keeps mutating (new samples appended, stale ones trimmed) on the
        # model, independently of when this widget last redrew.
        self.history = list(history)
        self.current_time = current_time
        self.pinned = pinned
        self.window_start = window_start

        self.update()

    def clear(self):

        self.set_history([], None)

    def wheelEvent(self, event):

        direction = 1 if event.angleDelta().y() > 0 else -1

        self.zoom_requested.emit(direction)

        event.accept()

    def visible_history(self):

        if self.window_start is None:
            return self.history

        return [(time, rssi) for time, rssi in self.history if time >= self.window_start]

    def paintEvent(self, event):

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Base))

        history = self.visible_history()

        if len(history) < 2:
            self.draw_placeholder(painter)
            return

        self.draw_graph(painter, history)

    def draw_placeholder(self, painter):

        text_color = self.palette().color(QPalette.ColorRole.Text)
        text_color.setAlpha(140)

        painter.setPen(text_color)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No RSSI data yet")

    @classmethod
    def compute_scale(cls, min_value, max_value):
        """Fixed default range, widened only if real data actually falls
        outside it — see DEFAULT_MIN_RSSI/DEFAULT_MAX_RSSI above. This also
        guarantees the returned span is never zero (the two defaults are 30
        apart), so a flat line (min_value == max_value) never divides by
        zero. Split out from draw_graph so the auto-widening behavior is
        unit-testable without a real paint device."""

        scale_min = min(cls.DEFAULT_MIN_RSSI, min_value)
        scale_max = max(cls.DEFAULT_MAX_RSSI, max_value)

        return scale_min, scale_max

    @staticmethod
    def compute_stats(history):
        """(min, max, avg) RSSI over history, or None for an empty one —
        for the header's summary label, split out for the same reason as
        compute_scale (unit-testable without a real paint device)."""

        if not history:
            return None

        values = [rssi for _, rssi in history]

        return min(values), max(values), sum(values) / len(values)

    @classmethod
    def marked_point_indices(cls, points):
        """Indices of points where at least one neighboring gap is wide
        enough (see MIN_MARKER_GAP) to mark individually — split out for
        the same reason as compute_scale/compute_stats (unit-testable
        without a real paint device). Works on plotted x-coordinates, not
        raw sample timestamps, since spacing-on-screen is what actually
        risks a visual smear."""

        marked = set()

        for i in range(len(points) - 1):

            if points[i + 1].x() - points[i].x() >= cls.MIN_MARKER_GAP:
                marked.add(i)
                marked.add(i + 1)

        return marked

    def draw_shape(self, painter, point, shape):

        r = self.MARKER_HALF_SIZE
        x, y = point.x(), point.y()

        if shape == "square":
            painter.drawRect(QRectF(x - r, y - r, r * 2, r * 2))

        elif shape == "diamond":
            diamond = QPolygonF(
                [QPointF(x, y - r), QPointF(x + r, y), QPointF(x, y + r), QPointF(x - r, y)]
            )
            painter.drawPolygon(diamond)

        elif shape == "cross":
            painter.drawLine(QPointF(x - r, y - r), QPointF(x + r, y + r))
            painter.drawLine(QPointF(x - r, y + r), QPointF(x + r, y - r))

        else:  # "circle", and the fallback for an unrecognized value
            painter.drawEllipse(point, r, r)

    def set_marker_pen_and_brush(self, painter, color):
        """A cross is drawn as two strokes (needs a pen, no fill); the
        solid shapes are drawn as a filled outline-free blob (needs a
        brush, no pen) — switching on shape here keeps draw_shape() itself
        agnostic to which one is active."""

        if self.marker_shape == "cross":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(color)
            pen.setWidthF(1.2)
            painter.setPen(pen)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)

    def draw_point_markers(self, painter, points, color):

        indices = self.marked_point_indices(points)

        if not indices:
            return

        self.set_marker_pen_and_brush(painter, color)

        for i in indices:
            self.draw_shape(painter, points[i], self.marker_shape)

    def draw_endpoint_marker(self, painter, point, color):

        self.set_marker_pen_and_brush(painter, color)
        self.draw_shape(painter, point, self.marker_shape)

    def draw_axis_ticks(self, painter, points, line_bottom, color):

        pen = QPen(color)
        pen.setWidthF(1.0)
        painter.setPen(pen)

        tick_top = line_bottom + 2
        tick_bottom = tick_top + 4

        for point in points:
            painter.drawLine(QPointF(point.x(), tick_top), QPointF(point.x(), tick_bottom))

    def draw_graph(self, painter, history):

        values = [rssi for _, rssi in history]
        min_value = min(values)
        max_value = max(values)

        scale_min, scale_max = self.compute_scale(min_value, max_value)
        span = scale_max - scale_min

        start_time = history[0][0]
        end_time = self.current_time or history[-1][0]
        duration = (end_time - start_time).total_seconds() or 1

        plot_left = self.MARGIN
        plot_right = self.width() - self.MARGIN
        plot_top = self.MARGIN
        plot_bottom = self.height() - self.MARGIN
        plot_width = max(plot_right - plot_left, 1)

        # The line's own vertical range is inset from plot_top/plot_bottom
        # by the text padding above — plot_top/plot_bottom themselves stay
        # the anchors the scale_max/scale_min text is drawn from, unchanged.
        # TIME_AXIS_PADDING carves out one more row below that, for the
        # oldest-sample-age/"now" labels drawn at the very end of this
        # method.
        line_top = plot_top + self.TOP_TEXT_PADDING
        line_bottom = plot_bottom - self.BOTTOM_TEXT_PADDING - self.TIME_AXIS_PADDING
        line_height = max(line_bottom - line_top, 1)

        def to_point(time, rssi):

            x = plot_left + ((time - start_time).total_seconds() / duration) * plot_width
            y = line_bottom - ((rssi - scale_min) / span) * line_height

            return QPointF(x, y)

        points = [to_point(time, rssi) for time, rssi in history]

        line_color = self.pinned_color if self.pinned else self.vessel_color

        pen = QPen(line_color)
        pen.setWidthF(1.5)
        painter.setPen(pen)

        for a, b in zip(points, points[1:]):
            painter.drawLine(a, b)

        if self.show_point_markers:
            self.draw_point_markers(painter, points, line_color)

        if self.show_endpoint_marker:
            self.draw_endpoint_marker(painter, points[-1], line_color)

        if self.show_axis_ticks:
            self.draw_axis_ticks(painter, points, line_bottom, line_color)

        painter.setBrush(Qt.BrushStyle.NoBrush)

        caption_color = self.palette().color(QPalette.ColorRole.Text)
        caption_color.setAlpha(180)
        painter.setPen(caption_color)

        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        # Scale endpoints together on the left (the y-axis) — top =
        # scale_max, bottom = scale_min — so both ends of the axis are read
        # from the same edge instead of hunting opposite corners. scale_min
        # sits right under the line's own bottom edge (line_bottom), not
        # plot_bottom — plot_bottom now anchors the time-axis row below it.
        painter.drawText(plot_left, plot_top + 8, f"{scale_max}")
        painter.drawText(plot_left, line_bottom + self.BOTTOM_TEXT_PADDING - 2, f"{scale_min}")

        # Most recent value on the opposite (right) side — min/max/avg live
        # in the section header now (see MainWindow.format_rssi_stats), so
        # aren't repeated here.
        metrics = painter.fontMetrics()

        last_sample_time, last_value = history[-1]
        stale_seconds = (end_time - last_sample_time).total_seconds()

        # A vessel with a slow reporting cadence (e.g. an anchored Class B
        # unit, once every 180s) can easily have its last actual sample be
        # a while before "now" — the line correctly stops there rather than
        # extending to the right edge, but without this, that gap just
        # looks like missing/broken data. "last" rather than "current" —
        # calling a 20s-old reading "current" reads as contradictory once
        # its age is spelled out right next to it. STALE_CAPTION_THRESHOLD
        # skips the near-zero case (a reading from mere fractions of a
        # second ago) where spelling it out would just be noise.
        if stale_seconds > self.STALE_CAPTION_THRESHOLD:
            caption = f"last {last_value} ({format_age(stale_seconds)})"
        else:
            caption = f"current {last_value}"

        painter.drawText(plot_right - metrics.horizontalAdvance(caption), plot_top + 8, caption)

        # Time axis: which side is "now" isn't otherwise obvious, especially
        # having just jumped to an arbitrary point in a long replay — newest
        # data is on the right (to_point() maps start_time to plot_left,
        # end_time to plot_right), so labeled accordingly here.
        age_label = format_age(duration)
        now_label = "now"

        painter.drawText(plot_left, plot_bottom - 2, age_label)
        painter.drawText(plot_right - metrics.horizontalAdvance(now_label), plot_bottom - 2, now_label)
