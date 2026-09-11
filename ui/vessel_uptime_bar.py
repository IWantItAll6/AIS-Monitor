from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtGui import QPainter, QColor, QPalette
from PySide6.QtCore import Qt, QRectF

from services.vessel_uptime import UptimeState
from ui.time_format import format_age

STATE_COLORS = {
    UptimeState.GREEN: QColor("#2ECC71"),
    UptimeState.AMBER: QColor("#F1C40F"),
    UptimeState.RED: QColor("#E74C3C"),
}


class VesselUptimeBar(QWidget):
    """Uptime-Kuma-style status strip: solid colored blocks along a time
    axis (no line, no numeric scale — the data is a discrete state, not a
    continuous quantity, so a sparkline-style line would falsely imply
    smooth transitions between states that don't exist). Shares MARGIN and
    the format_age()/"now" labeling convention with RssiGraphWidget so the
    two align when stacked."""

    # bar_top(MARGIN) + BAR_HEIGHT + LABEL_BASELINE_OFFSET leaves a few px
    # of clearance below the label's baseline for descenders before HEIGHT
    # runs out.
    HEIGHT = 36
    MARGIN = 6
    BAR_HEIGHT = 16
    LABEL_BASELINE_OFFSET = 11

    def __init__(self, parent=None):

        super().__init__(parent)

        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.segments = []
        self.current_time = None
        self.window_start = None

    def set_segments(self, segments, current_time, window_start=None):
        """window_start, when given, pins the bar's left edge to "now minus
        the configured track window" instead of whichever change point
        happens to be oldest — without it, a vessel that's stayed a single
        state (typically solid green) since before the window began never
        gets trimmed (VesselUptimeTracker.trim keeps one point for
        continuity), so the bar would otherwise keep stretching back to
        that vessel's first-ever sighting rather than staying bounded to
        the window, same as the RSSI graph and track length elsewhere."""

        self.segments = list(segments)
        self.current_time = current_time
        self.window_start = window_start

        self.update()

    def clear(self):

        self.set_segments([], None)

    def paintEvent(self, event):

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Base))

        if not self.segments or self.current_time is None:
            self.draw_placeholder(painter)
            return

        self.draw_bar(painter)

    def draw_placeholder(self, painter):

        text_color = self.palette().color(QPalette.ColorRole.Text)
        text_color.setAlpha(140)

        painter.setPen(text_color)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No uptime data")

    def draw_bar(self, painter):

        start_time = self.segments[0][0]

        if self.window_start is not None:
            start_time = max(start_time, self.window_start)

        end_time = self.current_time
        duration = (end_time - start_time).total_seconds() or 1

        plot_left = self.MARGIN
        plot_right = self.width() - self.MARGIN
        plot_width = max(plot_right - plot_left, 1)

        bar_top = self.MARGIN
        bar_bottom = bar_top + self.BAR_HEIGHT

        def x_at(time):
            return plot_left + ((time - start_time).total_seconds() / duration) * plot_width

        for seg_start, seg_end, state in self.segments:

            x0 = x_at(seg_start)
            x1 = x_at(seg_end)

            # A same-instant (zero-width) segment can occur right at a
            # report's arrival (see VesselUptimeTracker.record_report) —
            # skip it rather than draw an invisible sliver.
            if x1 <= x0:
                continue

            painter.fillRect(QRectF(x0, bar_top, x1 - x0, bar_bottom - bar_top), STATE_COLORS[state])

        caption_color = self.palette().color(QPalette.ColorRole.Text)
        caption_color.setAlpha(180)
        painter.setPen(caption_color)

        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        metrics = painter.fontMetrics()
        label_y = bar_bottom + self.LABEL_BASELINE_OFFSET

        age_label = format_age(duration)
        now_label = "now"

        painter.drawText(plot_left, label_y, age_label)
        painter.drawText(plot_right - metrics.horizontalAdvance(now_label), label_y, now_label)
