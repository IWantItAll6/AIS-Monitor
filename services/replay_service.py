import re
import time
from datetime import datetime, timedelta


def extract_sentence(line):
    """Strips the "[YYYY-MM-DD HH:MM:SS.ffffff] " prefix every recorded or
    replay-file line carries (see MainWindow.on_live_line_received) — a
    module-level function (not a ReplayService method) so both live/replay
    processing and the standalone file-analysis pass (which doesn't use a
    ReplayService instance at all) can parse this format identically."""

    match = re.match(r"^\[\d{4}-\d{2}-\d{2} .*?\]\s*(.*)$", line)

    if match:
        return match.group(1)

    return line


class ReplayService:

    def __init__(self):

        self.filename = None

        self.lines = []
        self.index = 0

        self.speed = 1

        self.start_time = None
        self.current_time = None

        # Wall-clock source for the replay clock below — an attribute rather
        # than a hard-wired time.monotonic() call so tests can drive it.
        self.clock = time.monotonic

        # (wall_seconds, log_time) pair the replay clock is measured from —
        # see anchor_clock(). None until playback's first timestamped batch.
        self._clock_anchor = None

    def load_file(self, filename):

        with open(filename, "r", encoding="utf-8", errors="ignore") as f:
            self.lines = f.readlines()

        self.filename = filename

        self.index = 0

        self.start_time = None
        self.current_time = None

        self._clock_anchor = None

    def has_next(self):

        return self.index < len(self.lines)

    def next_line(self):

        if not self.has_next():
            return None

        line = self.lines[self.index].rstrip()

        self.index += 1

        return line

    def next_batch(self):

        # Real receivers can emit several sentences at the exact same
        # instant (identical [timestamp] prefix, down to the millisecond)
        # — those should play back together rather than being spread out
        # one-per-tick by the pacing timer, so pull every consecutive line
        # that shares the next line's timestamp in one go.
        if not self.has_next():
            return []

        batch = [self.next_line()]
        first_ts = self.extract_timestamp(batch[0])

        while self.has_next():

            peek_ts = self.extract_timestamp(self.lines[self.index].rstrip())

            # `peek_ts != first_ts` alone is true even when both are None
            # (an unparseable/missing timestamp) — that let every consecutive
            # line with a bad timestamp merge into one unbounded batch,
            # instead of only genuinely-simultaneous, successfully-parsed
            # lines merging.
            if first_ts is None or peek_ts != first_ts:
                break

            batch.append(self.next_line())

        return batch

    def time_until_next_ms(self):

        # The real-world (unscaled by speed) gap between current_time — the
        # timestamp of whatever was just processed — and the next line
        # still queued up. Callers should only call this when has_next() is
        # true; a missing/unparseable timestamp on either side falls back
        # to 0 (play immediately) rather than stalling replay on bad data.
        if self.current_time is None:
            return 0

        next_ts = self.extract_timestamp(self.lines[self.index].rstrip())

        if next_ts is None:
            return 0

        return max(0, (next_ts - self.current_time).total_seconds() * 1000)

    def reset(self):

        self.index = 0

        self.start_time = None
        self.current_time = None

        self._clock_anchor = None

    # Replay clock: playback position is measured against wall-clock time
    # elapsed since an anchor point, not by chaining "wait the gap to the
    # next line" timers. Chained waits never account for the time spent
    # processing a batch and repainting in between, so every tick silently
    # added that overhead on top — on a busy real log, where a map repaint
    # alone takes a large fraction of the gap between messages, 2x/4x/10x
    # all collapsed to roughly real time. Measuring against the wall clock
    # lets the caller catch up by playing every batch that's already due.

    def anchor_clock(self):
        """Starts the replay clock at current_time, as of now. Called at the
        start of each play session (after Start/Resume), once the first
        timestamped batch has been played. No-op if nothing timestamped has
        been played yet."""

        self._clock_anchor = (self.clock(), self.current_time) if self.current_time else None

    def clear_clock(self):

        self._clock_anchor = None

    def clock_time(self):
        """The log time playback should have reached by now, or None if the
        clock isn't running."""

        if self._clock_anchor is None:
            return None

        wall_start, log_start = self._clock_anchor

        return log_start + timedelta(seconds=(self.clock() - wall_start) * self.speed)

    def next_batch_due(self):
        """Whether the next queued line's timestamp has already been
        reached by the replay clock — i.e. playback is behind and should
        play it now rather than wait. An unparseable timestamp counts as
        due, matching time_until_next_ms()'s "play immediately" fallback."""

        now = self.clock_time()

        if now is None or not self.has_next():
            return False

        next_ts = self.extract_timestamp(self.lines[self.index].rstrip())

        return next_ts is None or next_ts <= now

    def ms_until_next_due(self):
        """Real (speed-scaled) wait until the next queued line is due. Falls
        back to the plain gap-based wait when the clock isn't running."""

        now = self.clock_time()

        if now is None:
            return self.interval_ms(self.time_until_next_ms())

        next_ts = self.extract_timestamp(self.lines[self.index].rstrip())

        if next_ts is None:
            return 1

        return max(1, int((next_ts - now).total_seconds() * 1000 / self.speed))

    def _rebase_clock(self):

        # Re-anchor at the current clock position before a speed change —
        # otherwise the new speed would apply retroactively to all the wall
        # time elapsed since the anchor, jumping playback forward/back.
        now = self.clock_time()

        if now is not None:
            self._clock_anchor = (self.clock(), now)

    def speed_up(self):

        self._rebase_clock()
        self.speed += 1

    def slow_down(self):

        if self.speed > 1:
            self._rebase_clock()
            self.speed -= 1

    def interval_ms(self, base_interval_ms):

        # base_interval_ms is normally a real elapsed-time gap from
        # time_until_next_ms(), not a fixed constant — this just applies
        # the speed multiplier to it. A 0ms QTimer interval fires as fast
        # as the event loop allows rather than "instantly", so floor at
        # 1ms regardless of speed.
        return max(1, int(base_interval_ms / self.speed))

    def progress(self):

        if not self.lines:
            return 0

        return int((self.index / len(self.lines)) * 100)

    def extract_timestamp(self, line):

        # Matches the "[YYYY-MM-DD HH:MM:SS.ffffff] sentence" format every
        # recorded line is written in (see MainWindow.on_live_line_received).
        match = re.match(r"^\[(.*?)\]", line)

        if not match:
            return None

        try:
            return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S.%f")

        except Exception:
            return None

    def update_time(self, line):

        timestamp = self.extract_timestamp(line)

        if timestamp:

            self.current_time = timestamp

            if self.start_time is None:
                self.start_time = timestamp

        return timestamp
