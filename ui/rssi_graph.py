from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtGui import QPainter, QColor, QPen, QPalette
from PySide6.QtCore import Qt, QPointF

from ui.time_format import format_age


class RssiGraphWidget(QWidget):
    """Small hand-drawn sparkline of a vessel's RSSI over time — kept as a
    plain QPainter widget rather than pulling in a charting dependency, to
    match how MapPanel already hand-rolls its own rendering."""

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

    def __init__(self, parent=None):

        super().__init__(parent)

        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.vessel_color = QColor("#FF8C00")
        self.pinned_color = QColor("#FFD700")

        self.history = []
        self.current_time = None
        self.pinned = False

    def set_vessel_color(self, hex_color):

        self.vessel_color = QColor(hex_color)

        self.update()

    def set_pinned_color(self, hex_color):

        self.pinned_color = QColor(hex_color)

        self.update()

    def set_history(self, history, current_time, pinned=False):

        # Copied rather than referencing the deque directly — the deque
        # keeps mutating (new samples appended, stale ones trimmed) on the
        # model, independently of when this widget last redrew.
        self.history = list(history)
        self.current_time = current_time
        self.pinned = pinned

        self.update()

    def clear(self):

        self.set_history([], None)

    def paintEvent(self, event):

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Base))

        if len(self.history) < 2:
            self.draw_placeholder(painter)
            return

        self.draw_graph(painter)

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

    def draw_graph(self, painter):

        values = [rssi for _, rssi in self.history]
        min_value = min(values)
        max_value = max(values)

        scale_min, scale_max = self.compute_scale(min_value, max_value)
        span = scale_max - scale_min

        start_time = self.history[0][0]
        end_time = self.current_time or self.history[-1][0]
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

        points = [to_point(time, rssi) for time, rssi in self.history]

        line_color = self.pinned_color if self.pinned else self.vessel_color

        pen = QPen(line_color)
        pen.setWidthF(1.5)
        painter.setPen(pen)

        for a, b in zip(points, points[1:]):
            painter.drawLine(a, b)

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

        # min/current/max stats on the opposite (right) side.
        metrics = painter.fontMetrics()

        current_value = self.history[-1][1]
        caption = f"min {min_value}  ·  current {current_value}  ·  max {max_value}"

        painter.drawText(plot_right - metrics.horizontalAdvance(caption), plot_top + 8, caption)

        # Time axis: which side is "now" isn't otherwise obvious, especially
        # having just jumped to an arbitrary point in a long replay — newest
        # data is on the right (to_point() maps start_time to plot_left,
        # end_time to plot_right), so labeled accordingly here.
        age_label = format_age(duration)
        now_label = "now"

        painter.drawText(plot_left, plot_bottom - 2, age_label)
        painter.drawText(plot_right - metrics.horizontalAdvance(now_label), plot_bottom - 2, now_label)
