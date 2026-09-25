import threading
from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import QThread, Signal

from parsers.ais_parser import AISParser
from parsers.psmt_parser import PSMTParser
from parsers.gnss_parser import GNSSParser
from services.vessel_registry import VesselRegistry
from services.replay_service import ReplayService, extract_sentence
from services.geo import calculate_range_bearing
from services.ais_reporting_intervals import (
    expected_interval_seconds, update_low_speed_streak, CLASS_A_MSG_TYPES, CLASS_B_MSG_TYPES,
    SAR_AIRCRAFT_MSG_TYPES,
)

POSITION_REPORT_MSG_TYPES = CLASS_A_MSG_TYPES + CLASS_B_MSG_TYPES + SAR_AIRCRAFT_MSG_TYPES


@dataclass
class VesselAnalysis:
    """Per-vessel statistics accumulated over a full file — deliberately a
    separate accumulator from models.vessel.Vessel rather than extending it,
    since these fields (tx_count, running RSSI/speed sums, distance
    traveled) have no meaning for the live app's Vessel, which only ever
    holds current/trimmed state."""

    mmsi: int

    name: str = ""
    callsign: str = ""

    tx_count: int = 0

    first_seen: datetime | None = None
    last_seen: datetime | None = None

    rssi_min: int | None = None
    rssi_max: int | None = None
    rssi_sum: int = 0
    rssi_count: int = 0

    speed_sum: float = 0.0
    speed_count: int = 0

    distance_traveled_nm: float = 0.0

    range_min_nm: float | None = None
    range_max_nm: float | None = None

    # Full, untrimmed (datetime, lat, lon) history for this name-period —
    # same shape as models.vessel.Vessel.track — so "show this vessel's
    # complete journey" has real data to draw, unlike the live app's own
    # track which is bounded by the Track Length setting.
    track: list = field(default_factory=list)

    # expected_tx is a fractional running sum (each gap between reports
    # contributes gap_seconds / interval_at_that_time, not a whole number),
    # rounded only for display. position_report_count is deliberately
    # separate from tx_count above: tx_count includes every message type
    # (static data included), but expected_tx only models position-report
    # cadence, so comparing it against tx_count would be comparing
    # different things. Measured to add no meaningful runtime cost (all
    # real-log timing deltas were within measurement noise), so — unlike
    # the rest of this file's stats, none of which are optional — this
    # always runs; there's no "skip it to go faster" tradeoff to expose.
    expected_tx: float = 0.0
    position_report_count: int = 0

    # Not part of the public result shape — just bookkeeping so
    # distance_traveled_nm/expected_tx can be accumulated incrementally (one
    # running sum) rather than storing every position/report and summing at
    # the end.
    _last_position: tuple | None = field(default=None, repr=False)
    _last_report_time: datetime | None = field(default=None, repr=False)
    _last_report_interval_seconds: float | None = field(default=None, repr=False)

    # See services.ais_reporting_intervals.update_low_speed_streak — kept
    # in sync with the live VesselUptimeTracker's own tracking of the same
    # thing, so a file-analysis pass over a recorded session estimates the
    # exact same expected interval live tracking would have for it.
    _low_speed_since: datetime | None = field(default=None, repr=False)

    @property
    def duration_seconds(self):

        if self.first_seen is None or self.last_seen is None:
            return 0

        return (self.last_seen - self.first_seen).total_seconds()

    @property
    def avg_rssi(self):

        return self.rssi_sum / self.rssi_count if self.rssi_count else None

    @property
    def avg_speed(self):

        return self.speed_sum / self.speed_count if self.speed_count else None

    @property
    def estimated_tx_loss_percent(self):
        """None until at least one gap between two comparable reports has
        been observed (expected_tx starts at 0 and only a real gap grows
        it) — distinct from a genuine 0% loss. Not clamped at 0: a negative
        value is possible and meaningful — it means the vessel reported
        *faster* than the interval implied by its speed at the start of a
        gap predicted, most often because it sped up or began maneuvering
        partway through that gap. That's the approximation's own visible
        error, not a bug to hide."""

        if self.expected_tx <= 0:
            return None

        return (self.expected_tx - self.position_report_count) / self.expected_tx * 100


def format_duration(seconds):
    """12345 -> "3h 25m". Rounds down to whole minutes below an hour, whole
    hours+minutes at or above one — plenty of precision for "how long was
    this vessel in range", and matches the granularity AIS reporting
    intervals already operate at (seconds-level precision would be noise)."""

    seconds = int(seconds)

    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes:02d}m"

    return f"{minutes}m {secs:02d}s"


def analyze_file(filename, cancel_event=None, progress_callback=None, progress_interval=1000):
    """Parses a saved AIS/GNSS/PSMT replay log into full, untrimmed
    per-vessel statistics — completely independent of any live MainWindow
    state. This matters: the live app's registry continuously trims vessel
    track/RSSI history (track_length setting) and purges vessels after
    vessel_timeout, both purely to keep the live map/graph performant, not
    to be a complete record. Reusing that state here would make the same
    file produce different stats depending on whatever those settings
    happened to be — so this builds its own fresh registry/parsers and
    never trims or times anything out.

    cancel_event (a threading.Event) is checked every line — cheap enough
    not to throttle, unlike progress_callback(lines_processed, total_lines)
    which fires only every progress_interval lines, since a long file means
    a lot of calls and this is typically a cross-thread Qt signal emit.

    Returns a list of VesselAnalysis sorted by MMSI, or None if cancelled.
    """

    replay = ReplayService()
    replay.load_file(filename)

    total_lines = len(replay.lines)

    registry = VesselRegistry()
    ais_parser = AISParser(registry)
    psmt_parser = PSMTParser()
    gnss_parser = GNSSParser()

    # Keyed by (mmsi, name) rather than mmsi alone — field trials reuse the
    # same MMSI for different, differently-named test vessels within one
    # file, and merging their stats under one row would be meaningless.
    # Messages before any name is known (blank name — normal for Class B,
    # or before a static-data message arrives, not a "different vessel")
    # land under (mmsi, "") and get folded into the first real name that
    # shows up for that MMSI, rather than staying a permanent blank row.
    analyses = {}
    last_analysis_key = None
    own_position = {"lat": None, "lon": None, "fix": False}

    def route_analysis(mmsi, name):

        name = name or ""
        key = (mmsi, name)

        if key not in analyses:

            unnamed_key = (mmsi, "")

            if name and unnamed_key in analyses:
                analyses[key] = analyses.pop(unnamed_key)
                analyses[key].name = name

            else:
                analyses[key] = VesselAnalysis(mmsi=mmsi, name=name)

        return key, analyses[key]

    while replay.has_next():

        if cancel_event is not None and cancel_event.is_set():
            return None

        line = replay.next_line()

        timestamp = replay.update_time(line)
        sentence = extract_sentence(line)

        if progress_callback is not None and replay.index % progress_interval == 0:
            progress_callback(replay.index, total_lines)

        if sentence.startswith("!AIVDM"):

            vessel = ais_parser.process(sentence, timestamp)

            if vessel:

                last_analysis_key, analysis = route_analysis(vessel.mmsi, vessel.name)

                analysis.callsign = vessel.callsign
                analysis.tx_count += 1

                if timestamp is not None:

                    if analysis.first_seen is None:
                        analysis.first_seen = timestamp

                    analysis.last_seen = timestamp

                # vessel is the shared, persistent per-mmsi object the AIS
                # parser keeps — sog/lat/lon stay set to whatever a past
                # position report last put there even while processing a
                # later static-data (type 5/24) message, which carries
                # none of those fields itself. Without this guard, a
                # static-data message interleaved between position reports
                # would silently re-add that stale, unchanged speed/position
                # a second time — inflating avg_speed and, since the split
                # by name above (route_analysis), spuriously bleeding a
                # position from one name-period into the very start of the
                # next before it's ever received its own real report.
                is_position_report = ais_parser.last_msg_type in POSITION_REPORT_MSG_TYPES

                if is_position_report and vessel.sog is not None:
                    analysis.speed_sum += vessel.sog
                    analysis.speed_count += 1

                if is_position_report and vessel.lat is not None and vessel.lon is not None:

                    if analysis._last_position is not None:

                        distance_nm, _ = calculate_range_bearing(
                            *analysis._last_position, vessel.lat, vessel.lon
                        )

                        analysis.distance_traveled_nm += distance_nm

                    analysis._last_position = (vessel.lat, vessel.lon)
                    analysis.track.append((timestamp, vessel.lat, vessel.lon))

                    if own_position["fix"]:

                        range_nm, _ = calculate_range_bearing(
                            own_position["lat"], own_position["lon"], vessel.lat, vessel.lon
                        )

                        analysis.range_min_nm = (
                            range_nm if analysis.range_min_nm is None else min(analysis.range_min_nm, range_nm)
                        )
                        analysis.range_max_nm = (
                            range_nm if analysis.range_max_nm is None else max(analysis.range_max_nm, range_nm)
                        )

                if timestamp is not None:
                    analysis._low_speed_since, sustained_low_speed = update_low_speed_streak(
                        analysis._low_speed_since, timestamp, vessel.sog
                    )
                else:
                    sustained_low_speed = False

                interval = expected_interval_seconds(
                    ais_parser.last_msg_type, ais_parser.last_cs, vessel.sog, vessel.nav_status, sustained_low_speed
                )

                # A report type with no modeled reporting-rate rule (static
                # data, base station, AtoN) can't be compared — skip it
                # rather than let it silently distort the gap either as the
                # start or end of a "comparable" span.
                if interval is not None:

                    if timestamp is not None and analysis._last_report_time is not None:

                        gap_seconds = (timestamp - analysis._last_report_time).total_seconds()

                        # The interval implied by the *earlier* report's
                        # speed — held constant across the gap, since
                        # that's all a receive-only stream can know about
                        # what happened during it. This is the estimate's
                        # core, stated approximation.
                        analysis.expected_tx += gap_seconds / analysis._last_report_interval_seconds

                    analysis.position_report_count += 1
                    analysis._last_report_time = timestamp
                    analysis._last_report_interval_seconds = interval

        elif sentence.startswith("!AIVDO"):

            # Own-ship's echoed transmission — decode it (SOG/COG etc. are
            # harmless to update) but it isn't a received target, so it
            # deliberately doesn't touch last_ais_mmsi/tx_count/etc.,
            # mirroring MainWindow.route_sentence.
            ais_parser.process(sentence, timestamp)

        elif sentence.startswith("$PSMT"):

            psmt = psmt_parser.process(sentence)

            if psmt and last_analysis_key is not None:

                analysis = analyses[last_analysis_key]
                rssi = psmt["rssi"]

                analysis.rssi_sum += rssi
                analysis.rssi_count += 1
                analysis.rssi_min = rssi if analysis.rssi_min is None else min(analysis.rssi_min, rssi)
                analysis.rssi_max = rssi if analysis.rssi_max is None else max(analysis.rssi_max, rssi)

        elif sentence.startswith("$GP") or sentence.startswith("$GN"):

            position = gnss_parser.process(sentence)

            if position:
                own_position = position

    if progress_callback is not None:
        progress_callback(total_lines, total_lines)

    # first_seen can be None only if the file has no parseable timestamps
    # at all for that entry — datetime.min keeps those sortable rather than
    # raising on a None/datetime comparison.
    return sorted(analyses.values(), key=lambda a: (a.mmsi, a.first_seen or datetime.min))


def extract_rssi_history(lines, target_mmsi):
    """Full-file (timestamp, rssi) history for one vessel, independent of
    whatever MainWindow.trim_vessel_rssi_history has kept live — reuses
    analyze_file()'s "last AIVDM MMSI, then correlate the next PSMT to it"
    pattern, scoped to a single MMSI and an already-loaded line list (no
    file re-read, no VesselAnalysis/stats bookkeeping needed). `lines` is
    the same raw, un-rstripped list ReplayService.load_file() produces
    (e.g. an already-loaded ReplayService's own .lines)."""

    replay = ReplayService()

    ais_parser = AISParser(VesselRegistry())
    psmt_parser = PSMTParser()

    history = []
    last_mmsi = None

    for raw_line in lines:

        line = raw_line.rstrip()

        timestamp = replay.update_time(line)
        sentence = extract_sentence(line)

        if sentence.startswith("!AIVDM"):

            vessel = ais_parser.process(sentence, timestamp)

            if vessel:
                last_mmsi = vessel.mmsi

        elif sentence.startswith("$PSMT"):

            psmt = psmt_parser.process(sentence)

            if psmt and last_mmsi == target_mmsi:
                history.append((timestamp, psmt["rssi"]))

    return history


class FileAnalysisThread(QThread):
    """Runs analyze_file() off the GUI thread. Worth it: a continuous 2-day
    capture at real-world traffic density extrapolates to roughly 1.5M
    lines (measured against a real ~3.5hr/110K-line field log) — at this
    app's ~48K lines/sec processing rate that's on the order of 30s, long
    enough to freeze the whole UI if run inline."""

    progress = Signal(int, int)  # (lines_processed, total_lines)
    finished_analysis = Signal(list)
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, filename):

        super().__init__()

        self.filename = filename
        self._cancel_event = threading.Event()

    def cancel(self):

        self._cancel_event.set()

    def run(self):

        try:

            result = analyze_file(
                self.filename,
                cancel_event=self._cancel_event,
                progress_callback=lambda done, total: self.progress.emit(done, total)
            )

        except Exception as e:
            self.failed.emit(str(e))
            return

        if result is None:
            self.cancelled.emit()
        else:
            self.finished_analysis.emit(result)
