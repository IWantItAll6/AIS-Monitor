import re
from datetime import datetime

class ReplayService:

    def __init__(self):

        self.filename = None

        self.lines = []
        self.index = 0

        self.speed = 1

        self.start_time = None
        self.current_time = None

    def load_file(self, filename):

        with open(filename, "r", encoding="utf-8", errors="ignore") as f:
            self.lines = f.readlines()

        self.filename = filename

        self.index = 0

        self.start_time = None
        self.current_time = None

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

            if peek_ts != first_ts:
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

    def speed_up(self):

        self.speed += 1

    def slow_down(self):

        if self.speed > 1:
            self.speed -= 1

    def interval_ms(self, base_interval_ms):

        # A 0ms QTimer interval fires as fast as the event loop allows
        # rather than "instantly" — floor it at 1ms regardless of speed.
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
