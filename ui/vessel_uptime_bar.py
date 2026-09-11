from datetime import datetime, timedelta

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtGui import QPainter, QColor, QPalette
from PySide6.QtCore import Qt, QRectF, Signal

from services.vessel_uptime import UptimeState
from ui.time_format import format_age

STATE_COLORS = {
    UptimeState.GREEN: QColor("#2ECC71"),
    UptimeState.AMBER: QColor("#F1C40F"),
    UptimeState.RED: QColor("#E74C3C"),
}

# Priority ranking for collapsing multiple ticks/reports into one bucket's
# single color (see draw_bar/worst_state_in) — NOT a plain "worst wins"
# severity scale, despite the name matching that pattern:
#
# - RED beats everything, always. It means "confirmed missed" (past grace),
#   and a report arriving mere milliseconds past the grace window produces
#   a genuinely-recorded but sub-pixel-wide RED sliver that would otherwise
#   be invisible next to a much wider AMBER/GREEN span in the same bucket —
#   bucketing exists specifically so that doesn't get lost.
# - GREEN beats AMBER. AMBER only means "overdue but still within grace",
#   not "confirmed anything" — if the same bucket also contains a GREEN
#   (a report that actually arrived, on schedule or resolved before ever
#   going red), that's positive evidence overriding an otherwise-uncertain
#   AMBER elsewhere in the same bucket. Without this, a vessel keeping up
#   just barely — bouncing GREEN/AMBER without ever truly failing — reads
#   as a solid wall of AMBER instead of "basically fine."
# - AMBER only wins when it's the *only* state present in the bucket.
SEVERITY = {
    UptimeState.AMBER: 0,
    UptimeState.GREEN: 1,
    UptimeState.RED: 2,
}


class VesselUptimeBar(QWidget):
    """Uptime-Kuma-style status strip: solid colored blocks along a time
    axis (no line, no numeric scale — the data is a discrete state, not a
    continuous quantity, so a sparkline-style line would falsely imply
    smooth transitions between states that don't exist). Shares MARGIN and
    the format_age()/"now" labeling convention with RssiGraphWidget so the
    two align when stacked."""

    # See RssiGraphWidget.zoom_requested — same shared zoom, same reason.
    zoom_requested = Signal(int)

    # bar_top(MARGIN) + BAR_HEIGHT + LABEL_BASELINE_OFFSET leaves a few px
    # of clearance below the label's baseline for descenders before HEIGHT
    # runs out.
    HEIGHT = 36
    MARGIN = 6
    BAR_HEIGHT = 16
    LABEL_BASELINE_OFFSET = 11

    # Bucket count is derived from the widget's actual pixel width to hit
    # this target slot size, rather than a fixed count — so a narrow panel
    # doesn't cram in sub-pixel bars and a wide one doesn't end up with
    # only a handful of chunky ones; both instead get consistently-sized
    # bubbles, just more or fewer of them.
    TARGET_SLOT_WIDTH = 8
    BUCKET_GAP = 2
    CORNER_RADIUS = 1.5

    # Arbitrary but fixed reference point for bucket-grid alignment (see
    # draw_bar) — any fixed value works, since only *differences* from it
    # are ever used; picked to predate any real AIS data this app will
    # ever be pointed at.
    GRID_EPOCH = datetime(2000, 1, 1)

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

    def wheelEvent(self, event):

        direction = 1 if event.angleDelta().y() > 0 else -1

        self.zoom_requested.emit(direction)

        event.accept()

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

        bucket_count = max(1, round(plot_width / self.TARGET_SLOT_WIDTH))

        # window_start (when given) makes the *window itself* a fixed span
        # ("now" minus the track-length setting) rather than one that grows
        # every repaint while a vessel's own history is still shorter than
        # it — using that fixed span, not the data-bounded `duration` above,
        # keeps bucket_seconds constant across repaints. Without that
        # (window_start is None under an "Unlimited" track length, which has
        # no fixed span to anchor to at all), duration is the best available
        # stand-in, with the same drift this whole scheme otherwise avoids.
        if self.window_start is not None:
            window_seconds = (end_time - self.window_start).total_seconds() or 1
        else:
            window_seconds = duration

        bucket_seconds = window_seconds / bucket_count

        painter.setPen(Qt.PenStyle.NoPen)

        first_index = self.bucket_index(start_time, bucket_seconds)
        last_index = self.bucket_index(end_time, bucket_seconds)

        for index in range(first_index, last_index + 1):

            bucket_start, bucket_end = self.bucket_bounds(index, bucket_seconds)

            state = self.worst_state_in(bucket_start, bucket_end)

            if state is None:
                continue

            x0 = x_at(bucket_start)
            x1 = x_at(bucket_end)

            rect = QRectF(x0 + self.BUCKET_GAP / 2, bar_top, max(x1 - x0 - self.BUCKET_GAP, 1), bar_bottom - bar_top)

            painter.setBrush(STATE_COLORS[state])
            painter.drawRoundedRect(rect, self.CORNER_RADIUS, self.CORNER_RADIUS)

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

    def bucket_index(self, time, bucket_seconds):
        """Which fixed-grid bucket `time` falls into, anchored to
        GRID_EPOCH rather than to this paint's own start_time/duration —
        the latter re-anchors every repaint as "now" advances, so the same
        historical moment could land in a different bucket (and a
        different-*width* bucket, if duration itself was still growing)
        from one repaint to the next. That showed up as real flicker: a
        stretch of red visibly changing from spanning 4 buckets to 3 and
        back, with no underlying data change — just the grid being redrawn
        from scratch under it each time. Anchoring to a fixed grid means a
        given moment always maps to the same bucket regardless of when
        this paints; only the *range* of buckets currently in view shifts
        as the window slides, old ones scrolling off the left and new ones
        appearing on the right, exactly like Uptime Kuma's own bars."""

        return int((time - self.GRID_EPOCH).total_seconds() // bucket_seconds)

    def bucket_bounds(self, index, bucket_seconds):

        bucket_start = self.GRID_EPOCH + timedelta(seconds=index * bucket_seconds)

        return bucket_start, bucket_start + timedelta(seconds=bucket_seconds)

    def worst_state_in(self, bucket_start, bucket_end):
        """The highest-priority state (RED > GREEN > AMBER, see SEVERITY —
        not a plain worst-wins scale, despite the name) among those
        overlapping [bucket_start, bucket_end) — None if nothing does, which
        only happens for a bucket entirely before this vessel's earliest
        recorded data (segments are otherwise contiguous with no gaps)."""

        winner = None

        for seg_start, seg_end, state in self.segments:

            if seg_end <= bucket_start or seg_start >= bucket_end:
                continue

            if winner is None or SEVERITY[state] > SEVERITY[winner]:
                winner = state

        return winner
