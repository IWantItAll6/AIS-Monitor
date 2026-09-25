from collections import Counter, deque


# Short descriptions for the Message Statistics breakdown, per ITU-R
# M.1371 message type number.
MESSAGE_TYPE_NAMES = {
    1: "Position report (Class A)",
    2: "Position report (Class A, assigned)",
    3: "Position report (Class A, interrogated)",
    4: "Base station report",
    5: "Static and voyage data (Class A)",
    6: "Binary addressed message",
    7: "Binary acknowledge",
    8: "Binary broadcast message",
    9: "SAR aircraft position report",
    10: "UTC/date inquiry",
    11: "UTC/date response",
    12: "Addressed safety message",
    13: "Safety acknowledge",
    14: "Safety broadcast message",
    15: "Interrogation",
    16: "Assignment mode command",
    17: "DGNSS broadcast",
    18: "Position report (Class B)",
    19: "Extended position report (Class B)",
    20: "Data link management",
    21: "Aid to Navigation report",
    22: "Channel management",
    23: "Group assignment command",
    24: "Static data (Class B)",
    25: "Single slot binary message",
    26: "Multiple slot binary message",
    27: "Long-range position report",
}

# Which kind of station a message type identifies its sender as. Types not
# listed here (binary, safety, interrogation...) can come from any kind of
# station, so they say nothing about the sender's class.
STATION_CLASS_BY_MSG_TYPE = {
    1: "Class A", 2: "Class A", 3: "Class A", 5: "Class A",
    18: "Class B", 19: "Class B", 24: "Class B",
    4: "Base station",
    9: "SAR aircraft",
    21: "Aid to Navigation",
}

STATION_CLASSES = ("Class A", "Class B", "Base station", "SAR aircraft", "Aid to Navigation")

# Receiver-wide rate: a minute is short enough to show a receiver going
# quiet promptly, and a busy channel has plenty of messages in it.
RECEIVER_RATE_WINDOW_SECONDS = 60

# Per-vessel rate: longer, since a slow Class B only reports every 30s-3min
# and a one-minute window would flicker between 0, 1 and 2.
VESSEL_RATE_WINDOW_SECONDS = 300

# Below this much elapsed time a rate is mostly noise (one message in the
# first second reads as 60/min), so it's reported as unknown instead.
MIN_RATE_SPAN_SECONDS = 10


def message_type_name(msg_type):

    return MESSAGE_TYPE_NAMES.get(msg_type, "Unknown")


class MessageCounter:
    """A running message count plus a rolling messages-per-minute rate,
    over the last window_seconds of *message* time (the replay clock during
    replay), so replayed files report the rate they were recorded at rather
    than the playback speed."""

    def __init__(self, window_seconds):

        self.window_seconds = window_seconds
        self.count = 0
        self.first_time = None
        self.recent_times = deque()

    def record(self, time):

        self.count += 1

        if self.first_time is None:
            self.first_time = time

        self.recent_times.append(time)
        self._prune(time)

    def _prune(self, now):

        while self.recent_times and (now - self.recent_times[0]).total_seconds() > self.window_seconds:
            self.recent_times.popleft()

    def rate_per_minute(self, now):
        """Messages per minute over the last window_seconds, or None if
        fewer than MIN_RATE_SPAN_SECONDS have passed since the first message
        (too little data for a meaningful rate). Until a full window has
        passed, the rate is taken over the time actually elapsed rather
        than the whole window, so it doesn't start artificially low."""

        if self.first_time is None or now is None:
            return None

        self._prune(now)

        span = min(self.window_seconds, (now - self.first_time).total_seconds())

        if span < MIN_RATE_SPAN_SECONDS:
            return None

        return len(self.recent_times) * 60 / span


class MessageStatistics:
    """Receiver-wide message statistics for the session: total count and
    rate, a count per message type, and which class of station each MMSI
    heard has identified itself as."""

    def __init__(self):

        self.reset()

    def reset(self):

        self.counter = MessageCounter(RECEIVER_RATE_WINDOW_SECONDS)
        self.type_counts = Counter()
        self.station_classes = {}

    @property
    def total(self):

        return self.counter.count

    def record(self, time, msg_type, mmsi):

        self.counter.record(time)
        self.type_counts[msg_type] += 1

        station_class = STATION_CLASS_BY_MSG_TYPE.get(msg_type)

        if station_class is not None and mmsi:
            self.station_classes[mmsi] = station_class

    def rate_per_minute(self, now):

        return self.counter.rate_per_minute(now)

    def station_class_counts(self):
        """Number of distinct MMSIs heard per station class, in
        STATION_CLASSES order. An MMSI whose messages so far never said
        which class it is (e.g. only binary messages) isn't counted."""

        counts = Counter(self.station_classes.values())

        return [(station_class, counts[station_class]) for station_class in STATION_CLASSES]

    def type_breakdown(self):
        """(msg_type, name, count, percent) rows, most frequent first."""

        total = self.total

        return [
            (msg_type, message_type_name(msg_type), count, count * 100 / total)
            for msg_type, count in self.type_counts.most_common()
        ]
