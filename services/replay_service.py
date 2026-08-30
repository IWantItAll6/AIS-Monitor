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
