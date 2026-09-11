from enum import Enum

from services.ais_reporting_intervals import expected_interval_seconds, update_low_speed_streak

# How far beyond the nominal reporting interval to tolerate before treating
# a transmission as genuinely missed, rather than just running late (busy-
# channel slot contention, propagation, etc.). Matches the order of
# magnitude of ITU-R M.1371's own "increased reporting interval" fallback
# for Class B SO in a crowded channel (up to 2x nominal) — applied
# uniformly across station types as a documented simplification, the same
# spirit as ais_reporting_intervals.py's own simplifications.
GRACE_MULTIPLIER = 2.0


class UptimeState(Enum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"


class VesselUptimeTracker:
    """Tracks whether a vessel's position reports are arriving on schedule,
    overdue, or missed — a live, per-vessel accumulator kept separate from
    models.vessel.Vessel's own fields, the same way rssi_history/track are
    domain data while this is closer to derived, presentation-adjacent
    state (in spirit; still Qt-free, so it lives in services/, not ui/).

    Once elapsed time has pushed a period into RED, that verdict never
    changes; AMBER can still be retroactively folded back into GREEN by a
    later report — see record_report()'s docstring for why. change_points
    is a run-length-encoded history
    ([(time, state), ...], one entry per *change*, not one per tick),
    kept intentionally small: a vessel that stays GREEN forever holds a
    single entry regardless of session length.
    """

    def __init__(self):

        self.change_points = []

        self._last_report_time = None
        self._last_interval_seconds = None

        # See update_low_speed_streak() — reset to None the moment a
        # report comes in above LOW_SPEED_THRESHOLD_KN.
        self._low_speed_since = None

    def _current_state(self, now):

        if self._last_report_time is None or self._last_interval_seconds is None:
            return None

        elapsed = (now - self._last_report_time).total_seconds()
        grace_seconds = self._last_interval_seconds * GRACE_MULTIPLIER

        if elapsed <= self._last_interval_seconds:
            return UptimeState.GREEN

        if elapsed <= grace_seconds:
            return UptimeState.AMBER

        return UptimeState.RED

    def _record_state(self, time, state):

        if state is None:
            return

        if not self.change_points or self.change_points[-1][1] != state:
            self.change_points.append((time, state))

    def record_report(self, time, msg_type, cs_flag, speed_kn, nav_status=None):
        """Call when a position report arrives.

        RED is never rewritten: past the grace period, a receiver can't
        tell "that specific transmission was merely late" apart from "one
        or more transmissions were actually missed and this is just the
        next one on schedule" — both look identical once more than one
        interval has passed, so whatever RED already happened stays
        exactly as it was recorded at the time.

        AMBER is different: it means "overdue but still within the grace
        tolerance", not "confirmed missed". If a report arrives while still
        in that window, nothing was actually lost — it was just a slow
        transmission (busy-channel slot contention, etc.) — so the AMBER
        period is retroactively folded back into GREEN rather than left as
        a false "degraded" mark.

        Also tracks (via update_low_speed_streak) how long speed_kn has
        stayed at/below the low-speed threshold, independent of nav_status,
        so a Class A vessel that's plainly been sitting still for a while
        gets the anchored/moored 180s interval even if its nav_status is
        stuck on "Undefined" (common in practice — see
        ais_reporting_intervals.py).
        """

        self._low_speed_since, sustained_low_speed = update_low_speed_streak(
            self._low_speed_since, time, speed_kn
        )

        interval = expected_interval_seconds(msg_type, cs_flag, speed_kn, nav_status, sustained_low_speed)

        # Not a report type with a modeled reporting-rate rule (static
        # data, base station, AtoN) — nothing to compare, so this vessel's
        # uptime tracking is untouched by it either way.
        if interval is None:
            return

        if self._current_state(time) == UptimeState.AMBER:
            if self.change_points and self.change_points[-1][1] == UptimeState.AMBER:
                self.change_points.pop()
        else:
            self.tick(time)

        self._last_report_time = time
        self._last_interval_seconds = interval

        self._record_state(time, UptimeState.GREEN)

    def tick(self, now):
        """Call periodically (e.g. on the existing 1s UI timer) even when
        no report has arrived, so a vessel that's gone quiet still
        progresses GREEN -> AMBER -> RED from elapsed time alone, not only
        when a new message happens to trigger a check."""

        self._record_state(now, self._current_state(now))

    def segments(self, now):
        """[(start, end, UptimeState), ...] for rendering, oldest first —
        the last segment's end is `now` (it's still open/ongoing)."""

        result = []

        for i, (start, state) in enumerate(self.change_points):

            end = self.change_points[i + 1][0] if i + 1 < len(self.change_points) else now

            result.append((start, end, state))

        return result

    def uptime_percentage(self, now, window_start=None):
        """% of the window spent GREEN — AMBER and RED both count against
        it, matching the intuitive "was it reporting on schedule" reading
        rather than a stricter "confirmed missed only" one. window_start
        clips the window the same way VesselUptimeBar's display window
        does (pass the same value so the header % and the bar it sits
        above always agree); defaults to the tracker's own earliest
        change point — i.e. its whole recorded history — when omitted.

        None if there's no data to measure yet.
        """

        segments = self.segments(now)

        if not segments:
            return None

        start = segments[0][0]

        if window_start is not None:
            start = max(start, window_start)

        total_seconds = (now - start).total_seconds()

        if total_seconds <= 0:
            return None

        green_seconds = 0.0

        for seg_start, seg_end, state in segments:

            seg_start = max(seg_start, start)

            if seg_end <= seg_start:
                continue

            if state == UptimeState.GREEN:
                green_seconds += (seg_end - seg_start).total_seconds()

        return (green_seconds / total_seconds) * 100.0

    def trim(self, cutoff_time):
        """Drops change points entirely before cutoff_time, except the
        last one at-or-before it — that one still describes the state in
        effect at the start of the retained window, the same "keep one
        for continuity" idea as MainWindow.trim_track, just applied to a
        sparse change-point list instead of a dense sample deque."""

        keep_from = 0

        for i, (time, _) in enumerate(self.change_points):

            if time <= cutoff_time:
                keep_from = i
            else:
                break

        self.change_points = self.change_points[keep_from:]
