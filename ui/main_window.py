from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QTextEdit,
    QFrame,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QStatusBar,
    QGridLayout,
    QToolBar,
    QFileDialog,
    QMessageBox,
    QCheckBox,
    QSizePolicy,
    QApplication,
    QWidgetAction,
    QSlider,
    QToolTip,
    QLineEdit
)

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QIcon, QCursor, QAction, QKeySequence
import re
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

from ui.communications_dialog import CommunicationsDialog
from ui.preferences_dialog import PreferencesDialog
from ui.help_dialog import HelpDialog
from ui.about_dialog import AboutDialog
from ui.error_log_dialog import ErrorLogDialog
from services.error_log import ErrorLog
from services.settings_service import SettingsService
from services.vessel_registry import VesselRegistry
from parsers.ais_parser import AISParser
from parsers.gnss_parser import GNSSParser
from parsers.psmt_parser import PSMTParser
from services.geo import calculate_range_bearing, format_distance, convert_distance
from ui.vessel_tree_item import VesselTreeItem
from services.replay_service import ReplayService
from ui.map_panel import MapPanel
from services.theme_service import apply_theme, apply_title_bar_theme
from services.serial_reader import SerialReaderThread
from services.session_recorder import SessionRecorder


class MainWindow(QMainWindow):

    # How long the accelerated "show where things came from" preroll
    # animation takes in wall-clock time when landing on a scrubbed
    # position, regardless of how much simulated time it covers.
    SCRUB_ANIMATION_MS = 2500

    def __init__(self):
        super().__init__()

        self.settings = SettingsService.load()

        apply_theme(QApplication.instance(), self.settings["theme"])
        apply_title_bar_theme(self, self.settings["theme"])

        self.current_mode = "Stopped"

        self.setWindowTitle("AIS Monitor")
        self.setWindowIcon(QIcon("assets/app_icon.png"))
        self.resize(1400, 900)

        self.restore_window_geometry()

        self.replay = ReplayService()

        self.serial_readers = []
        self.recorder = SessionRecorder(self.settings["recordings_folder"])

        # update_status() runs very frequently (every seen_timer tick and
        # every AIS message via update_target_tree), so a plain timed
        # showMessage() would be overwritten almost instantly — this text
        # is folded into update_status()'s own message instead, and cleared
        # by a timer, so it actually stays readable.
        self.status_warning = None

        self.own_position = {
            "lat": None,
            "lon": None,
            "fix": False
        }

        self.registry = VesselRegistry()

        self.own_track = deque()

        self.error_log = ErrorLog()

        self.ais_parser = AISParser(self.registry, self.error_log)
        self.gnss_parser = GNSSParser()
        self.psmt_parser = PSMTParser(self.error_log)

        self.setup_ui()

        self.create_toolbar()
        self.selected_mmsi = None
        # self.add_test_targets()
        self.create_menu()
        self.replay_time = None
        self.replay.speed = 1

        self.target_tree.itemClicked.connect(self.on_vessel_selected)
        self.target_tree.itemDoubleClicked.connect(self.on_vessel_double_clicked)
        self.map_view.vessel_clicked.connect(self.on_map_vessel_clicked)
        self.map_view.vessel_double_clicked.connect(self.toggle_vessel_pin)
        # exit_replay_action is already connected in create_toolbar() —
        # connecting it again here was a duplicate, making every Exit
        # Replay click run exit_replay() twice.

        self.replay.filename = None

        # Single-shot, not repeating: each firing reschedules itself for a
        # different delay (the real gap to the next timestamp — see
        # replay_next_line), rather than ticking at one fixed interval.
        self.replay_timer = QTimer()
        self.replay_timer.setSingleShot(True)

        self.replay_timer.timeout.connect(self.replay_next_line)

        # Set by pause_clicked(), consumed by start_clicked() — see there.
        self._paused_remaining_ms = None

        self.last_ais_mmsi = None

        self.seen_timer = QTimer()

        self.seen_timer.timeout.connect(self.update_target_tree)

        self.seen_timer.start(1000)

        self.scrub_timer = QTimer()

        self.scrub_timer.timeout.connect(self.scrub_animation_step)

        self._scrub_target_index = None
        self._scrub_lines_per_frame = 1

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QVBoxLayout()
        central.setLayout(root_layout)

        splitter = self.splitter = QSplitter(Qt.Orientation.Horizontal)

        root_layout.addWidget(splitter)

        #
        # MAP PANEL
        #

        self.map_panel = QFrame()
        self.map_panel.setFrameShape(QFrame.Shape.Box)

        map_layout = QVBoxLayout()
        self.map_panel.setLayout(map_layout)

        self.map_view = MapPanel(
            "data/naturalearth/ne_10m_land/ne_10m_land.shp",
            "data/naturalearth/ne_10m_populated_places/ne_10m_populated_places_simple.shp",
            "data/geonames/gb_towns.json"
        )

        self.map_view.set_distance_unit(self.settings["distance_unit"])
        self.map_view.set_vessel_color(self.settings["vessel_color"])
        self.map_view.set_pinned_color(self.settings["pinned_color"])
        self.map_view.set_show_place_names(self.settings["show_place_names"])
        self.map_view.set_coastal_filter(
            self.settings["coastal_towns_only"], float(self.settings["coastal_threshold_nm"])
        )

        map_layout.addWidget(self.map_view)

        splitter.addWidget(self.map_panel)

        #
        # TARGET PANEL
        #

        self.targets_panel = QFrame()
        self.targets_panel.setFrameShape(QFrame.Shape.Box)

        target_layout = QVBoxLayout()
        self.targets_panel.setLayout(target_layout)

        self.targets_label = QLabel("Targets (3)")
        target_layout.addWidget(self.targets_label)

        self.target_search = QLineEdit()
        self.target_search.setPlaceholderText("Search by MMSI or name…")
        self.target_search.setClearButtonEnabled(True)
        self.target_search.textChanged.connect(self.apply_target_filter)
        target_layout.addWidget(self.target_search)

        self.target_tree = QTreeWidget()
        self.tree_items = {}
        self.target_tree.setHeaderLabels(["★", "MMSI", "Name", "Range", "Bearing", "RSSI", "Seen"])

        self.target_tree.setColumnWidth(0, 25)  # Star
        self.target_tree.setColumnWidth(1, 95)  # MMSI
        self.target_tree.setColumnWidth(3, 85)  # Range
        self.target_tree.setColumnWidth(4, 65)  # Bearing
        self.target_tree.setColumnWidth(5, 55)  # RSSI
        self.target_tree.setColumnWidth(6, 55)  # Seen

        from PySide6.QtWidgets import QHeaderView

        header = self.target_tree.header()

        header.setStretchLastSection(False)

        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        target_layout.addWidget(self.target_tree)

        self.target_tree.setSortingEnabled(True)
        self.target_tree.setAlternatingRowColors(True)

        details_widget = QWidget()

        details_layout = QGridLayout()
        details_widget.setLayout(details_layout)

        self.detail_mmsi = QLabel("-")
        self.detail_name = QLabel("-")
        self.detail_callsign = QLabel("-")
        self.detail_type = QLabel("-")
        self.detail_position = QLabel("-")
        self.detail_sog = QLabel("-")
        self.detail_cog = QLabel("-")
        self.detail_heading = QLabel("-")
        self.detail_nav_status = QLabel("-")
        self.detail_range = QLabel("-")
        self.detail_bearing = QLabel("-")
        self.detail_rssi = QLabel("-")
        self.detail_seen = QLabel("-")
        self.detail_destination = QLabel("-")
        self.detail_draught = QLabel("-")
        self.detail_imo = QLabel("-")
        self.detail_rot = QLabel("-")
        self.detail_length = QLabel("-")
        self.detail_beam = QLabel("-")

        title = QLabel("Selected Vessel")
        font = title.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        title.setFont(font)

        details_layout.addWidget(title, 0, 0)

        # Every field here is independently toggleable from View > Vessel
        # Detail Fields (see apply_detail_field_visibility). default_visible
        # keeps the originally-always-shown fields visible out of the box;
        # the fields added later (Destination onward) default off since most
        # users don't need them.
        self.DETAIL_FIELDS = [
            ("MMSI", "MMSI:", self.detail_mmsi, True),
            ("Name", "Name:", self.detail_name, True),
            ("Callsign", "Callsign:", self.detail_callsign, True),
            ("Type", "Type:", self.detail_type, True),
            ("Position", "Position:", self.detail_position, True),
            ("SOG", "SOG:", self.detail_sog, True),
            ("COG", "COG:", self.detail_cog, True),
            ("Heading", "Heading:", self.detail_heading, True),
            ("Nav Status", "Nav Status:", self.detail_nav_status, True),
            ("Range", "Range:", self.detail_range, True),
            ("Bearing", "Bearing:", self.detail_bearing, True),
            ("RSSI", "RSSI:", self.detail_rssi, True),
            ("Seen", "Seen:", self.detail_seen, True),
            ("Destination", "Destination:", self.detail_destination, False),
            ("Draught", "Draught:", self.detail_draught, False),
            ("IMO", "IMO:", self.detail_imo, False),
            ("Rate of Turn", "Rate of Turn:", self.detail_rot, False),
            ("Length", "Length:", self.detail_length, False),
            ("Beam", "Beam:", self.detail_beam, False),
        ]

        self.detail_field_captions = {}

        for i, (name, caption_text, value_label, default_visible) in enumerate(self.DETAIL_FIELDS):

            row = 1 + i // 2
            col = (i % 2) * 2

            caption_label = QLabel(caption_text)

            details_layout.addWidget(caption_label, row, col)
            details_layout.addWidget(value_label, row, col + 1)

            self.detail_field_captions[name] = caption_label

        target_layout.addWidget(details_widget)

        self.apply_detail_field_visibility()

        self.target_tree.setIndentation(0)
        self.target_tree.setRootIsDecorated(False)

        splitter.addWidget(self.targets_panel)

        splitter.setSizes(self.settings.get("splitter_sizes") or [850, 550])

        #
        # RAW DATA
        #

        raw_header_layout = QHBoxLayout()
        raw_header_layout.setContentsMargins(0, 0, 0, 0)

        self.raw_toggle = QPushButton("► Raw Data")

        self.raw_toggle.setCheckable(True)
        self.raw_toggle.toggled.connect(self.toggle_raw_data)
        self.raw_toggle.setMaximumWidth(120)

        raw_header_layout.addWidget(self.raw_toggle)

        self.raw_filter_widget = QWidget()

        filter_layout = QHBoxLayout()
        filter_layout.setContentsMargins(0, 0, 0, 0)
        self.raw_filter_widget.setLayout(filter_layout)

        filter_layout.addWidget(QLabel("Show:"))

        self.filter_ais_checkbox = QCheckBox("AIS")
        self.filter_gnss_checkbox = QCheckBox("GNSS")
        self.filter_rssi_checkbox = QCheckBox("RSSI")
        self.filter_other_checkbox = QCheckBox("Other")

        for checkbox in (
            self.filter_ais_checkbox,
            self.filter_gnss_checkbox,
            self.filter_rssi_checkbox,
            self.filter_other_checkbox
        ):
            checkbox.setChecked(True)
            filter_layout.addWidget(checkbox)

        self.raw_filter_widget.hide()
        self.raw_filter_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        raw_header_layout.addWidget(self.raw_filter_widget)
        raw_header_layout.addStretch()

        root_layout.addLayout(raw_header_layout)

        self.raw_data = QTextEdit()
        self.raw_data.setReadOnly(True)
        self.raw_data.setMaximumHeight(200)
        self.raw_data.hide()

        root_layout.addWidget(self.raw_data)

        #
        # STATUS BAR
        #

        self.status_bar = QStatusBar()

        self.setStatusBar(self.status_bar)

        self.update_status()

    def create_toolbar(self):

        toolbar = QToolBar()

        toolbar.setMovable(False)

        font = toolbar.font()
        font.setPointSize(font.pointSize() + 2)

        toolbar.setFont(font)

        self.addToolBar(toolbar)

        #
        # Main controls
        #

        self.start_action = toolbar.addAction("▶ Start")
        self.pause_action = toolbar.addAction("⏸ Pause")
        self.stop_action = toolbar.addAction("■ Stop")
        self.clear_action = toolbar.addAction("✖ Clear")

        toolbar.addSeparator()

        #
        # Map controls
        #

        self.center_gnss_action = toolbar.addAction("⊙ GNSS")

        toolbar.addSeparator()

        #
        # Replay controls
        #

        self.slower_action = toolbar.addAction("◀ Slower")

        self.speed_label = QLabel("1x")
        toolbar.addWidget(self.speed_label)

        self.faster_action = toolbar.addAction("Faster ▶")

        self.skip_to_end_action = toolbar.addAction("⏭ Skip to End")

        self.exit_replay_action = toolbar.addAction("⏏ Exit Replay")

        #
        # Replay progress / scrubber
        #

        self.replay_scrubber = QSlider(Qt.Orientation.Horizontal)

        self.replay_scrubber.setMinimumWidth(200)
        self.replay_scrubber.setMaximumWidth(300)
        self.replay_scrubber.setEnabled(False)

        self.replay_scrubber.sliderPressed.connect(self.scrubber_pressed)
        self.replay_scrubber.sliderMoved.connect(self.scrubber_moved)
        self.replay_scrubber.sliderReleased.connect(self.scrubber_released)

        self.faster_action.triggered.connect(self.faster_clicked)
        self.slower_action.triggered.connect(self.slower_clicked)
        toolbar.addWidget(self.replay_scrubber)
        self.replay_time_label = QLabel("--:--:--")
        toolbar.addWidget(self.replay_time_label)

        self.animate_scrub_checkbox = QCheckBox("Animate on drop")
        self.animate_scrub_checkbox.setChecked(True)
        self.animate_scrub_checkbox.setToolTip(
            "When landing on a scrubbed position, briefly replay the Track "
            "Length window leading up to it so you can see where vessels "
            "came from, instead of jumping straight to a static snapshot."
        )
        toolbar.addWidget(self.animate_scrub_checkbox)

        #
        # Initial button states
        #

        self.start_action.setEnabled(True)
        self.pause_action.setEnabled(False)
        self.stop_action.setEnabled(False)

        self.slower_action.setEnabled(False)
        self.faster_action.setEnabled(False)
        self.skip_to_end_action.setEnabled(False)
        self.exit_replay_action.setEnabled(False)

        #
        # Signals
        #

        self.start_action.triggered.connect(self.start_clicked)
        self.pause_action.triggered.connect(self.pause_clicked)
        self.stop_action.triggered.connect(self.stop_clicked)
        self.clear_action.triggered.connect(self.clear_clicked)
        self.skip_to_end_action.triggered.connect(self.skip_to_end_clicked)
        self.exit_replay_action.triggered.connect(self.exit_replay)
        self.center_gnss_action.triggered.connect(self.center_on_gnss)

        #
        # Keyboard shortcuts — also listed with their command in the Run
        # menu (create_menu), which is the intended way to discover these
        # rather than needing to already know them.
        #

        self.start_action.setShortcut(QKeySequence("F5"))
        self.pause_action.setShortcut(QKeySequence("F6"))
        self.stop_action.setShortcut(QKeySequence("F7"))
        self.clear_action.setShortcut(QKeySequence("Ctrl+Shift+C"))
        self.center_gnss_action.setShortcut(QKeySequence("Ctrl+G"))
        self.skip_to_end_action.setShortcut(QKeySequence("Ctrl+End"))

        self.zoom_in_action = QAction("Zoom In", self)
        self.zoom_in_action.setShortcut(QKeySequence("Ctrl+="))
        self.zoom_in_action.triggered.connect(self.map_view.zoom_in)

        self.zoom_out_action = QAction("Zoom Out", self)
        self.zoom_out_action.setShortcut(QKeySequence("Ctrl+-"))
        self.zoom_out_action.triggered.connect(self.map_view.zoom_out)

        self.zoom_fit_action = QAction("Zoom to Fit", self)
        self.zoom_fit_action.setShortcut(QKeySequence("Ctrl+0"))
        self.zoom_fit_action.triggered.connect(self.map_view.fit_to_vessels)

    def start_clicked(self):

        self.seen_timer.start(1000)

        if self.replay.filename:

            # Checked before current_mode is overwritten below. Gating on
            # "was actually Paused", not just "is there a leftover
            # _paused_remaining_ms value", matters because pause_clicked()
            # isn't the only way out of Paused — e.g. clicking Stop instead
            # of Start would otherwise leave a stale remaining-time value
            # that a later, unrelated Start could wrongly resume with.
            resuming_from_pause = self.current_mode == "Paused" and self._paused_remaining_ms is not None

            self.current_mode = "Replay"

            if resuming_from_pause:
                # Pick up the real-time gap to the next batch where it left
                # off, rather than replaying that batch instantly — an
                # instant resume would silently fast-forward through
                # however much of the wait was left, undermining "1x means
                # real time" for exactly the case (pausing) most likely to
                # leave time pending.
                self.replay_timer.start(max(1, self._paused_remaining_ms))
                self._paused_remaining_ms = None

            else:
                self.replay_next_line()

        else:
            self.current_mode = "Live"
            self.start_live_serial()

        self.start_action.setEnabled(False)
        self.pause_action.setEnabled(True)
        self.stop_action.setEnabled(True)

        self.update_status()

    def start_live_serial(self):

        self.recorder.start()
        self.warn_if_recordings_folder_large()

        self.serial_readers = [self.make_serial_reader("ais")]

        if self.settings.get("use_separate_gnss"):
            self.serial_readers.append(self.make_serial_reader("gnss"))

        for reader in self.serial_readers:
            reader.start()

    def warn_if_recordings_folder_large(self):

        threshold = self.settings["recordings_warning_size_mb"]

        if threshold == "No warning":
            return

        size_mb = self.recorder.directory_size_mb()

        if size_mb >= float(threshold):
            self.status_warning = f"⚠ Recordings folder is {size_mb:.0f} MB"
            self.update_status()

            QTimer.singleShot(8000, self.clear_status_warning)

            QMessageBox.warning(
                self,
                "Recordings Folder Large",
                f"The recordings folder ({self.recorder.directory}) has grown to "
                f"{size_mb:.0f} MB. Old recordings are never deleted automatically — "
                "review and clean it up manually if needed, or raise/disable this "
                "warning in Preferences."
            )

    def make_serial_reader(self, prefix):

        reader = SerialReaderThread(
            self.settings[f"{prefix}_port"],
            int(self.settings[f"{prefix}_baud"]),
            self.settings[f"{prefix}_serial_format"]
        )

        reader.line_received.connect(self.on_live_line_received)
        reader.error_occurred.connect(self.on_serial_error)

        return reader

    def stop_live_serial(self):

        # Signal every reader to stop before blocking on any of them —
        # reader.stop() itself blocks the calling (GUI) thread up to 2s, and
        # calling it in a loop paid that up to once per reader (up to ~4s
        # with separate GNSS enabled) instead of overlapping their shutdowns.
        for reader in self.serial_readers:
            reader.request_stop()

        for reader in self.serial_readers:
            reader.wait(2000)

        self.serial_readers = []

        self.recorder.stop()

    def on_live_line_received(self, line):

        # Wrapping with the same "[timestamp] sentence" format the replay
        # files already use means this line can go through process_sentence
        # completely unchanged, and a recorded session is itself replayable.
        timestamped = f"[{datetime.now():%Y-%m-%d %H:%M:%S.%f}] {line}"

        self.recorder.write(timestamped)

        self.process_sentence(timestamped)

    def on_serial_error(self, message):

        # stop_clicked() sets the status bar's permanent message via
        # update_status() — show the temporary error overlay after that,
        # not before, or it gets immediately overwritten.
        self.stop_clicked()

        self.status_bar.showMessage(f"Serial error: {message}", 5000)

    def pause_clicked(self):

        # Captured before stop() cancels it — QTimer.remainingTime() is
        # -1/0 once stopped, so this has to happen first. Consumed by
        # start_clicked() to resume the real-time wait where it left off,
        # instead of instantly playing whatever batch was pending.
        self._paused_remaining_ms = (
            self.replay_timer.remainingTime() if self.replay_timer.isActive() else None
        )

        self.replay_timer.stop()
        self.scrub_timer.stop()
        self.seen_timer.stop()
        self.stop_live_serial()

        self.current_mode = "Paused"

        self.start_action.setEnabled(True)
        self.pause_action.setEnabled(False)
        self.stop_action.setEnabled(True)

        self.update_status()

    def stop_clicked(self):

        self.replay_timer.stop()

        # Otherwise a scrub animation in progress (see start_scrub_animation)
        # keeps firing after Stop, still calling process_sentence() on the
        # lines it was mid-way through — same class of bug as the one fixed
        # in clear_clicked() below: a stale timer surviving a reset and
        # silently continuing to advance/repopulate the session.
        self.scrub_timer.stop()

        self.seen_timer.stop()

        self.replay.reset()

        self.stop_live_serial()

        self.current_mode = "Stopped"

        self.start_action.setEnabled(True)
        self.pause_action.setEnabled(False)
        self.stop_action.setEnabled(False)

        self.update_status()

    def clear_clicked(self):

        # Deliberately does NOT touch replay position/timer, unlike
        # Stop — Clear wipes displayed session data while leaving an
        # active Live or Replay session running, same as it already leaves
        # live serial reading untouched. It used to also call
        # self.replay.reset(), which — since clear_action stays enabled
        # during active replay, unlike start/pause/stop — silently rewound
        # a running replay's position without stopping its pending timer,
        # so it would keep ticking and immediately restart playback from
        # the beginning right after a Clear mid-replay.
        self.reset_session()
        self.raw_data.clear()

    def faster_clicked(self):

        self.replay.speed_up()

        self.speed_label.setText(f"{self.replay.speed}x")

    def slower_clicked(self):

        self.replay.slow_down()

        self.speed_label.setText(f"{self.replay.speed}x")

    def replay_next_line(self):

        # Also the landing spot for "ran out of lines" after a batch below
        # (rather than duplicating this block there): that schedules an
        # essentially-immediate next call, which lands back here with
        # has_next() now false.
        if not self.replay.has_next():

            self.replay.reset()

            self.stop_clicked()

            QMessageBox.information(self, "Replay Complete", "Replay file has reached the end.")

            return

        # A batch, not one line: several sentences sharing the exact same
        # embedded timestamp (as real receivers do emit) should play back
        # together, not be spread out one-per-tick.
        for line in self.replay.next_batch():
            self.process_sentence(line)

        self.replay_scrubber.setValue(self.replay.index)

        self.raw_data.verticalScrollBar().setValue(self.raw_data.verticalScrollBar().maximum())

        if self.replay.has_next():
            # Real elapsed time to the next distinct timestamp, scaled by
            # the current speed multiplier — this is what makes "1x" mean
            # actual real-time playback instead of a fixed lines-per-second
            # rate (see ReplayService.time_until_next_ms).
            self.replay_timer.start(self.replay.interval_ms(self.replay.time_until_next_ms()))

        else:
            # Nothing left to time a wait against — let the next tick
            # (fired essentially immediately) hit the has_next() guard
            # above and stop cleanly.
            self.replay_timer.start(1)

    def process_sentence(self, line):

        sentence = self.extract_sentence(line)

        # Filtering only affects what's shown here — nothing about what
        # gets processed or (once session recording exists) logged to disk.
        if self.should_display_sentence(sentence):
            self.raw_data.append(line)

        timestamp = self.replay.update_time(line)

        if timestamp and hasattr(self,"replay_time_label"):
            self.replay_time_label.setText(timestamp.strftime("%Y-%m-%d %H:%M:%S"))

        self.route_sentence(sentence)

    def should_display_sentence(self, sentence):

        if sentence.startswith("!AI"):
            return self.filter_ais_checkbox.isChecked()

        if sentence.startswith("$G"):
            return self.filter_gnss_checkbox.isChecked()

        if sentence.startswith("$PSMT"):
            return self.filter_rssi_checkbox.isChecked()

        return self.filter_other_checkbox.isChecked()

    def route_sentence(self, sentence):

        if sentence.startswith("!AIVDM"):

            vessel = self.ais_parser.process(sentence, self.replay.current_time)

            if vessel:
                self.last_ais_mmsi = vessel.mmsi

                self.update_target_tree()

        elif sentence.startswith("!AIVDO"):

            # Own-ship's echoed position report — decode it like any other
            # vessel so its SOG/COG etc. are visible in the details panel,
            # but deliberately don't touch last_ais_mmsi: that's for
            # correlating $PSMT RSSI readings with a *received* transmission,
            # and our own outgoing one isn't that.
            vessel = self.ais_parser.process(sentence, self.replay.current_time)

            if vessel:
                self.update_target_tree()

        elif sentence.startswith("$PSMT"):

            psmt = self.psmt_parser.process(sentence)

            if psmt and self.last_ais_mmsi is not None:

                vessel = self.registry.get(self.last_ais_mmsi)

                if vessel:
                    vessel.rssi = psmt["rssi"]
                    self.update_target_tree()

        elif sentence.startswith("$GP"):

            position = self.gnss_parser.process(sentence)

            if position:
                self.record_own_position(position)

                self.update_status()

        elif sentence.startswith("$GN"):

            position = self.gnss_parser.process(sentence)

            if position:
                self.record_own_position(position)

                self.update_status()

    def record_own_position(self, position):

        self.own_position = position

        if position.get("fix") and position.get("lat") is not None and position.get("lon") is not None:

            current_time = self.replay.current_time or datetime.now()

            self.own_track.append((current_time, position["lat"], position["lon"]))

    def extract_sentence(self, line):

        match = re.match(r"^\[\d{4}-\d{2}-\d{2} .*?\]\s*(.*)$", line)

        if match:
            return match.group(1)

        return line

    def format_seen(self, vessel):

        if self.replay.current_time is None:
            return "-"

        last_seen = vessel.last_seen

        if last_seen is None:
            return "-"

        age = int((self.replay.current_time - last_seen).total_seconds())

        seconds = age % 60

        if age < 60:
            return f"{seconds}s"

        if age < 3600:
            minutes = age // 60
            seconds = age % 60

            return f"{minutes}m {seconds}s"

        hours = age // 3600

        minutes = (age % 3600) // 60

        return f"{hours}h {minutes}m"

    def update_target_tree(self):

        self.check_vessel_timeouts()
        self.trim_vessel_tracks()
        self.trim_own_track()

        # Amend existing rows in place rather than clear()+rebuild, so the
        # tree's selection/focus survives a refresh instead of being lost
        # every time (clear() destroys and recreates every QTreeWidgetItem).
        current_mmsis = set(self.registry.vessels.keys())

        for mmsi in list(self.tree_items.keys()):

            if mmsi not in current_mmsis:

                item = self.tree_items.pop(mmsi)

                index = self.target_tree.indexOfTopLevelItem(item)

                if index != -1:
                    self.target_tree.takeTopLevelItem(index)

        for vessel in self.registry.all():

            range_text = ""
            bearing_text = ""

            if self.own_position["fix"] and vessel.lat is not None and vessel.lon is not None:
                rng, brg = calculate_range_bearing(
                    self.own_position["lat"], self.own_position["lon"], vessel.lat, vessel.lon
                )

                vessel.range = rng
                vessel.bearing = brg

                range_text = format_distance(rng, self.settings.get("distance_unit", "NM"))
                bearing_text = f"{brg:.0f}°"

            else:
                # Otherwise vessel.range/bearing keep their last-known
                # value indefinitely once the GNSS fix drops — the
                # displayed cell correctly goes blank, but the tree's own
                # Range-column sort order (and MapPanel's map-label
                # priority, which also reads vessel.range) would still be
                # silently ranking by stale data instead of "unknown".
                vessel.range = None
                vessel.bearing = None

            seen_text = self.format_seen(vessel)

            mmsi = vessel.mmsi

            if mmsi in self.tree_items:
                item = self.tree_items[mmsi]

            else:
                item = VesselTreeItem(["", "", "", "", "", "", ""])
                self.target_tree.addTopLevelItem(item)
                self.tree_items[mmsi] = item

            item.setText(0, "★" if vessel.pinned else "")
            item.setText(1, str(mmsi))
            item.setText(2, vessel.name)
            item.setText(3, range_text)
            item.setText(4, bearing_text)
            item.setText(5, str(vessel.rssi) if vessel.rssi is not None else "")
            item.setText(6, seen_text)

            # Pinned sort (see VesselTreeItem.__lt__ — always floats to top)
            item.setData(0, Qt.ItemDataRole.UserRole, vessel.pinned)

            # MMSI sort
            item.setData(1, Qt.ItemDataRole.UserRole, mmsi)

            # Range sort
            item.setData(3, Qt.ItemDataRole.UserRole, vessel.range if vessel.range is not None else 999999)

            # Bearing sort
            item.setData(4, Qt.ItemDataRole.UserRole, vessel.bearing if vessel.bearing is not None else 999)

            # RSSI sort
            item.setData(5, Qt.ItemDataRole.UserRole, vessel.rssi if vessel.rssi is not None else -999)

            # Seen sort — only meaningful when replay supplies a time
            # reference; live mode has none (see format_seen for the same gate).
            if self.replay.current_time is not None and vessel.last_seen is not None:

                age_seconds = (self.replay.current_time - vessel.last_seen).total_seconds()

                item.setData(6, Qt.ItemDataRole.UserRole, age_seconds)

        self.targets_label.setText(f"Targets ({len(self.registry.vessels)})")

        self.map_view.update_vessels(list(self.registry.all()), self.own_position, self.own_track)

        self.update_status()

        self.apply_target_filter()

        if self.selected_mmsi is not None:

            vessel = self.registry.get(self.selected_mmsi)

            if vessel:
                self.show_vessel_details(vessel)

    def apply_target_filter(self):

        query = self.target_search.text().strip().lower()

        for mmsi, item in self.tree_items.items():

            if not query:
                item.setHidden(False)
                continue

            vessel = self.registry.get(mmsi)

            name = (vessel.name or "").lower() if vessel else ""

            item.setHidden(query not in str(mmsi) and query not in name)

    def update_status(self):

        gnss_status = "Fix" if self.own_position["fix"] else "No Fix"

        logging_status = self.recorder.path.name if self.recorder.is_recording else "Stopped"

        message = (
            f"Mode: {self.current_mode} | "
            f"GNSS: {gnss_status} | "
            f"Targets: {len(self.registry.vessels)} | "
            f"Logging: {logging_status}"
        )

        if self.status_warning:
            message += f" | {self.status_warning}"

        # Persistent (not auto-clearing like status_warning) since it
        # reflects an actual running count for the session, not a one-off
        # notice — stays visible until the user clears it from the Session
        # Error Log dialog (Help menu).
        if self.error_log.entries:
            count = len(self.error_log.entries)
            message += f" | ⚠ {count} parse error{'s' if count != 1 else ''}"

        self.status_bar.showMessage(message)

        self.map_view.set_empty_hint(
            self.current_mode == "Stopped" and not self.replay.filename and not self.registry.vessels
        )

    def clear_status_warning(self):

        self.status_warning = None

        self.update_status()

    def closeEvent(self, event):

        self.stop_live_serial()

        self.save_window_geometry()

        event.accept()

    def restore_window_geometry(self):

        geometry = self.settings.get("window_geometry")

        if not geometry:
            return

        if geometry.get("maximized"):
            self.showMaximized()

        else:
            self.setGeometry(geometry["x"], geometry["y"], geometry["width"], geometry["height"])

    def save_window_geometry(self):

        # normalGeometry() (not geometry()) while maximized, so un-maximizing
        # next launch restores the size it had before maximizing rather than
        # the full-screen size.
        geom = self.normalGeometry() if self.isMaximized() else self.geometry()

        self.settings["window_geometry"] = {
            "x": geom.x(),
            "y": geom.y(),
            "width": geom.width(),
            "height": geom.height(),
            "maximized": self.isMaximized()
        }

        self.settings["splitter_sizes"] = self.splitter.sizes()

        SettingsService.save(self.settings)

    def show_communications(self):

        dialog = CommunicationsDialog(self.settings)
        apply_title_bar_theme(dialog, self.settings["theme"])

        if dialog.exec():
            SettingsService.save(self.settings)

    def show_preferences(self):

        dialog = PreferencesDialog(self.settings)
        apply_title_bar_theme(dialog, self.settings["theme"])

        if dialog.exec():
            SettingsService.save(self.settings)
            apply_theme(QApplication.instance(), self.settings["theme"])
            apply_title_bar_theme(self, self.settings["theme"])
            self.map_view.set_distance_unit(self.settings["distance_unit"])
            self.map_view.set_vessel_color(self.settings["vessel_color"])
            self.map_view.set_pinned_color(self.settings["pinned_color"])
            self.map_view.set_coastal_filter(
                self.settings["coastal_towns_only"], float(self.settings["coastal_threshold_nm"])
            )
            self.recorder.directory = Path(self.settings["recordings_folder"])

    def create_menu(self):
        menu = self.menuBar()

        file_menu = menu.addMenu("File")

        view_menu = menu.addMenu("View")

        run_menu = menu.addMenu("Run")

        # Reuses the exact same QAction objects already wired to the
        # toolbar buttons — a QAction can live in more than one place at
        # once, so this menu is purely a second, shortcut-labelled way to
        # reach the same commands, not a separate set to keep in sync.
        run_menu.addAction(self.start_action)
        run_menu.addAction(self.pause_action)
        run_menu.addAction(self.stop_action)
        run_menu.addAction(self.clear_action)

        run_menu.addSeparator()

        run_menu.addAction(self.center_gnss_action)
        run_menu.addAction(self.zoom_in_action)
        run_menu.addAction(self.zoom_out_action)
        run_menu.addAction(self.zoom_fit_action)

        run_menu.addSeparator()

        run_menu.addAction(self.slower_action)
        run_menu.addAction(self.faster_action)
        run_menu.addAction(self.skip_to_end_action)
        run_menu.addAction(self.exit_replay_action)

        settings_menu = menu.addMenu("Settings")

        self.show_raw_data_action = view_menu.addAction("Show Raw Data")
        self.show_raw_data_action.setCheckable(True)

        # Bidirectional sync with the toolbar toggle button — either control
        # can drive the other; setChecked() only re-emits toggled() when the
        # value actually changes, so this can't loop.
        self.show_raw_data_action.toggled.connect(self.raw_toggle.setChecked)
        self.raw_toggle.toggled.connect(self.show_raw_data_action.setChecked)

        self.show_place_names_action = view_menu.addAction("Show Place Names")
        self.show_place_names_action.setCheckable(True)
        self.show_place_names_action.setChecked(self.settings["show_place_names"])
        self.show_place_names_action.toggled.connect(self.set_show_place_names)

        columns_menu = view_menu.addMenu("Select Columns")

        column_names = ["Pinned", "MMSI", "Name", "Range", "Bearing", "RSSI", "Seen"]

        visible_columns = self.settings.get("visible_columns", {})

        for index, name in enumerate(column_names):

            visible = visible_columns.get(name, True)

            self.target_tree.setColumnHidden(index, not visible)

            checkbox = QCheckBox(name)
            checkbox.setChecked(visible)
            checkbox.toggled.connect(
                lambda checked, i=index, n=name: self.set_column_visible(i, n, checked)
            )

            # A QWidgetAction (real checkbox widget) rather than a checkable
            # QAction — clicking a plain QAction closes the menu, which would
            # force reopening it between every column toggle.
            action = QWidgetAction(columns_menu)
            action.setDefaultWidget(checkbox)

            columns_menu.addAction(action)

        detail_fields_menu = view_menu.addMenu("Vessel Detail Fields")

        visible_detail_fields = self.settings.get("visible_detail_fields", {})

        for name, caption_text, value_label, default_visible in self.DETAIL_FIELDS:

            visible = visible_detail_fields.get(name, default_visible)

            checkbox = QCheckBox(name)
            checkbox.setChecked(visible)
            checkbox.toggled.connect(
                lambda checked, n=name: self.set_detail_field_visible(n, checked)
            )

            # Same QWidgetAction pattern as Select Columns — a checkable
            # QAction would close the menu on every single toggle.
            action = QWidgetAction(detail_fields_menu)
            action.setDefaultWidget(checkbox)

            detail_fields_menu.addAction(action)

        self.communications_action = settings_menu.addAction("Communications")
        self.preferences_action = settings_menu.addAction("Preferences")

        self.communications_action.triggered.connect(self.show_communications)
        self.preferences_action.triggered.connect(self.show_preferences)

        self.open_replay_action = file_menu.addAction("Open Replay...")

        self.open_replay_action.triggered.connect(self.open_replay)
        self.open_replay_action.setShortcut(QKeySequence("Ctrl+O"))

        self.load_sample_action = file_menu.addAction("Load Sample Data")

        self.load_sample_action.triggered.connect(self.load_sample_data)

        export_menu = file_menu.addMenu("Export")

        self.export_screenshot_action = export_menu.addAction("Screenshot...")
        self.export_screenshot_action.triggered.connect(self.export_screenshot)

        self.export_targets_csv_action = export_menu.addAction("Target List as CSV...")
        self.export_targets_csv_action.triggered.connect(self.export_targets_csv)

        help_menu = menu.addMenu("Help")

        self.help_action = help_menu.addAction("Help")
        self.error_log_action = help_menu.addAction("Session Error Log")
        self.about_action = help_menu.addAction("About")

        self.help_action.triggered.connect(self.show_help)
        self.error_log_action.triggered.connect(self.show_error_log)
        self.about_action.triggered.connect(self.show_about)

    def show_help(self):

        dialog = HelpDialog()
        apply_title_bar_theme(dialog, self.settings["theme"])
        dialog.exec()

    def show_error_log(self):

        dialog = ErrorLogDialog(self.error_log)
        apply_title_bar_theme(dialog, self.settings["theme"])
        dialog.exec()

        # Clearing may have happened inside the dialog — reflect it in the
        # status bar immediately rather than waiting for the next tick.
        self.update_status()

    def show_about(self):

        dialog = AboutDialog()
        apply_title_bar_theme(dialog, self.settings["theme"])
        dialog.exec()

    def export_screenshot(self):

        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Screenshot", "screenshot.png", "PNG Image (*.png)"
        )

        if not filename:
            return

        # Whole window, not just the map — includes the target list and
        # detail panel too, per the user's explicit request.
        self.grab().save(filename, "PNG")

        self.status_bar.showMessage(f"Screenshot exported to {filename}", 5000)

    def export_targets_csv(self):

        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Target List as CSV", "targets.csv", "CSV File (*.csv)"
        )

        if not filename:
            return

        import csv

        unit = self.settings.get("distance_unit", "NM")

        with open(filename, "w", newline="", encoding="utf-8") as f:

            writer = csv.writer(f)

            writer.writerow([
                "MMSI", "Name", "Callsign", "Type", "Pinned",
                "Latitude", "Longitude", "SOG (kn)", "COG (deg)", "Heading (deg)",
                "Nav Status", f"Range ({unit})", "Bearing (deg)", "RSSI",
                "Last Seen",
                "Destination", "Draught (m)", "IMO", "Rate of Turn (deg/min)",
                "Length (m)", "Beam (m)"
            ])

            for vessel in self.registry.all():

                writer.writerow([
                    vessel.mmsi,
                    vessel.name or "",
                    vessel.callsign or "",
                    vessel.type or "",
                    vessel.pinned,
                    vessel.lat if vessel.lat is not None else "",
                    vessel.lon if vessel.lon is not None else "",
                    vessel.sog if vessel.sog is not None else "",
                    vessel.cog if vessel.cog is not None else "",
                    vessel.heading if vessel.heading is not None else "",
                    vessel.nav_status or "",
                    convert_distance(vessel.range, unit) if vessel.range is not None else "",
                    vessel.bearing if vessel.bearing is not None else "",
                    vessel.rssi if vessel.rssi is not None else "",
                    vessel.last_seen.strftime("%Y-%m-%d %H:%M:%S") if vessel.last_seen else "",
                    vessel.destination or "",
                    vessel.draught if vessel.draught is not None else "",
                    vessel.imo if vessel.imo is not None else "",
                    vessel.rot if vessel.rot is not None else "",
                    vessel.length if vessel.length is not None else "",
                    vessel.beam if vessel.beam is not None else ""
                ])

        self.status_bar.showMessage(f"Target list exported to {filename}", 5000)

    def set_column_visible(self, index, name, visible):

        self.target_tree.setColumnHidden(index, not visible)

        self.settings.setdefault("visible_columns", {})[name] = visible

        SettingsService.save(self.settings)

    def set_show_place_names(self, show):

        self.map_view.set_show_place_names(show)

        self.settings["show_place_names"] = show

        SettingsService.save(self.settings)

    def apply_detail_field_visibility(self):

        visible_fields = self.settings.get("visible_detail_fields", {})

        for name, caption_text, value_label, default_visible in self.DETAIL_FIELDS:

            visible = visible_fields.get(name, default_visible)

            self.detail_field_captions[name].setVisible(visible)
            value_label.setVisible(visible)

    def set_detail_field_visible(self, name, visible):

        self.settings.setdefault("visible_detail_fields", {})[name] = visible

        SettingsService.save(self.settings)

        self.apply_detail_field_visibility()

        # Newly-shown fields shouldn't sit blank until the next AIS message
        # for the selected vessel — refresh immediately from current data.
        if self.selected_mmsi is not None:

            vessel = self.registry.get(self.selected_mmsi)

            if vessel:
                self.show_vessel_details(vessel)

    def open_replay(self):

        start_dir = self.settings.get("last_replay_folder", "")

        filename, _ = QFileDialog.getOpenFileName(
            self, "Open Replay File", start_dir, "Log Files (*.txt *.log);;All Files (*)"
        )

        if not filename:
            return

        self.settings["last_replay_folder"] = str(Path(filename).parent)

        SettingsService.save(self.settings)

        self.load_replay_file(filename)

    def load_sample_data(self):

        sample_path = Path("resources/sample_replay.log")

        if not sample_path.exists():
            QMessageBox.warning(
                self, "Sample Data Missing",
                f"Could not find {sample_path} — it should be bundled with the app."
            )
            return

        self.load_replay_file(str(sample_path))

    def load_replay_file(self, filename):

        self.reset_session()

        self.replay.load_file(filename)

        self.replay.filename = filename
        self.replay.reset()
        self.current_mode = "Replay"
        self.slower_action.setEnabled(True)
        self.faster_action.setEnabled(True)
        self.skip_to_end_action.setEnabled(True)
        self.exit_replay_action.setEnabled(True)
        self.replay_scrubber.setMinimum(0)
        self.replay_scrubber.setMaximum(max(len(self.replay.lines) - 1, 0))
        self.replay_scrubber.setValue(0)
        self.replay_scrubber.setEnabled(True)
        self.update_status()

    def skip_to_end_clicked(self):

        if not self.replay.filename:
            return

        self.replay_timer.stop()
        self.seen_timer.stop()

        # A tight loop with no timer pacing — Qt coalesces the many
        # update()/repaint requests triggered along the way into a single
        # repaint once control returns to the event loop, so this is close
        # to as fast as the underlying parsing itself, not bottlenecked by
        # per-message UI rendering.
        while self.replay.has_next():

            line = self.replay.next_line()

            self.process_sentence(line)

        self.replay_scrubber.setValue(self.replay.index)

        self.current_mode = "Stopped"

        self.start_action.setEnabled(True)
        self.pause_action.setEnabled(False)
        self.stop_action.setEnabled(True)

        self.update_target_tree()

    def scrubber_pressed(self):

        self.replay_timer.stop()
        self.seen_timer.stop()
        self.scrub_timer.stop()

    def scrubber_moved(self, index):

        if not self.replay.lines:
            return

        index = max(0, min(index, len(self.replay.lines) - 1))

        timestamp = self.replay.extract_timestamp(self.replay.lines[index])

        if timestamp:
            QToolTip.showText(QCursor.pos(), timestamp.strftime("%Y-%m-%d %H:%M:%S"), self.replay_scrubber)

    def scrubber_released(self):

        self.seek_to_index(self.replay_scrubber.value())

    def seek_to_index(self, target_index):

        if not self.replay.filename or not self.replay.lines:
            return

        target_index = max(0, min(target_index, len(self.replay.lines) - 1))

        target_time = self.replay.extract_timestamp(self.replay.lines[target_index])

        self.reset_session()
        self.replay.reset()

        # Default: no animation, process straight through the target line
        # (inclusive) in the instant/silent loop below.
        preroll_start_index = target_index + 1

        track_setting = self.settings.get("track_length", "10")

        # "Unlimited" has no finite window to rewind by — fall back to an
        # instant landing rather than silently inventing an arbitrary
        # duration the user never configured.
        if self.animate_scrub_checkbox.isChecked() and target_time is not None and track_setting != "Unlimited":

            window_start = target_time - timedelta(minutes=int(track_setting))

            preroll_start_index = 0

            for i in range(target_index + 1):

                line_time = self.replay.extract_timestamp(self.replay.lines[i])

                if line_time is not None and line_time < window_start:
                    preroll_start_index = i + 1

                else:
                    break

            preroll_start_index = min(preroll_start_index, target_index)

        # Silently fast-forward (no timer pacing, same technique as Skip to
        # End) up to the start of the animated window — or straight to the
        # target if not animating.
        while self.replay.index < preroll_start_index:
            self.process_sentence(self.replay.next_line())

        self._scrub_target_index = target_index

        if self.replay.index <= target_index and self.replay.has_next():
            self.start_scrub_animation()

        else:
            self.finish_seek()

    def start_scrub_animation(self):

        remaining = max(self._scrub_target_index - self.replay.index + 1, 1)

        # Multiple lines get bundled into each frame — Qt only actually
        # repaints once per frame regardless of how many lines it contains
        # (repeated update() calls between event-loop turns get coalesced),
        # but each *timer fire* still costs a real event-loop turn, so a
        # dense window (thousands of messages) firing one line per tick
        # would take far longer than SCRUB_ANIMATION_MS in practice.
        # Bundling caps the number of ticks regardless of window density.
        frames = max(1, min(remaining, self.SCRUB_ANIMATION_MS // 50))

        self._scrub_lines_per_frame = -(-remaining // frames)  # ceil division

        interval = max(1, self.SCRUB_ANIMATION_MS // frames)

        self.map_view.set_scrub_animating(True)

        self.scrub_timer.start(interval)

    def scrub_animation_step(self):

        for _ in range(self._scrub_lines_per_frame):

            if not self.replay.has_next() or self.replay.index > self._scrub_target_index:
                break

            self.process_sentence(self.replay.next_line())

        self.replay_scrubber.setValue(min(self.replay.index, self._scrub_target_index))

        self.raw_data.verticalScrollBar().setValue(self.raw_data.verticalScrollBar().maximum())

        if not self.replay.has_next() or self.replay.index > self._scrub_target_index:
            self.scrub_timer.stop()
            self.finish_seek()

    def finish_seek(self):

        self.map_view.set_scrub_animating(False)

        self.replay_scrubber.setValue(self.replay.index)

        self.current_mode = "Stopped"

        self.start_action.setEnabled(True)
        self.pause_action.setEnabled(False)
        self.stop_action.setEnabled(True)

        self.update_target_tree()
        self.update_status()

    def exit_replay(self):

        self.stop_clicked()

        self.replay.filename = None

        self.slower_action.setEnabled(False)
        self.faster_action.setEnabled(False)
        self.skip_to_end_action.setEnabled(False)
        self.exit_replay_action.setEnabled(False)
        self.replay_scrubber.setEnabled(False)

        self.current_mode = "Stopped"

        self.update_status()

    def toggle_raw_data(self, checked):

        if checked:

            self.raw_toggle.setText("▼ Raw Data")
            self.raw_data.show()
            self.raw_filter_widget.show()

        else:

            self.raw_toggle.setText("► Raw Data")
            self.raw_data.hide()
            self.raw_filter_widget.hide()

    def add_test_targets(self):
        vessels = [
            ("★", "235123456", "SEA RANGER", "1.2nm", "034°", "-107", "2s"),
            ("★", "232456789", "PILOT ONE", "2.8nm", "212°", "-102", "5s"),
            ("", "311111111", "TUG ALPHA", "5.4nm", "180°", "-107", "32s")
        ]

        for vessel in vessels:
            item = QTreeWidgetItem(vessel)

            self.target_tree.addTopLevelItem(item)

    def on_vessel_selected(self, item, column):

        mmsi_text = item.text(1)

        if not mmsi_text:
            return

        mmsi = int(mmsi_text)

        if column == 0:
            self.toggle_vessel_pin(mmsi)
            return

        self.selected_mmsi = mmsi

        vessel = self.registry.get(mmsi)

        if vessel:
            self.show_vessel_details(vessel)

    def toggle_vessel_pin(self, mmsi):

        vessel = self.registry.get(mmsi)

        if vessel:
            vessel.pinned = not vessel.pinned
            self.update_target_tree()

    def on_vessel_double_clicked(self, item, column):

        mmsi_text = item.text(1)

        if not mmsi_text:
            return

        vessel = self.registry.get(int(mmsi_text))

        if vessel and vessel.lat is not None and vessel.lon is not None:
            self.map_view.set_center(vessel.lat, vessel.lon)

    def on_map_vessel_clicked(self, mmsi):

        item = self.tree_items.get(mmsi)

        if item:
            self.target_tree.setCurrentItem(item)

        self.selected_mmsi = mmsi

        vessel = self.registry.get(mmsi)

        if vessel:
            self.show_vessel_details(vessel)

    def center_on_gnss(self):

        if self.own_position.get("fix") and self.own_position.get("lat") is not None:
            self.map_view.set_center(self.own_position["lat"], self.own_position["lon"])

        else:
            self.status_bar.showMessage("No GNSS fix", 2000)

    def show_vessel_details(self, vessel):

        self.detail_mmsi.setText(str(vessel.mmsi))

        self.detail_name.setText(vessel.name or "-")

        if vessel.lat is None or vessel.lon is None:
            self.detail_position.setText("-")
        else:
            self.detail_position.setText(f"{vessel.lat}, {vessel.lon}")

        self.detail_sog.setText("-" if vessel.sog is None else f"{vessel.sog:.1f} kn")
        self.detail_cog.setText("-" if vessel.cog is None else f"{vessel.cog:.0f}°")

        self.detail_heading.setText(
            "-" if vessel.heading is None else f"{vessel.heading}°"
        )

        self.detail_nav_status.setText(vessel.nav_status or "-")

        self.detail_rssi.setText("-" if vessel.rssi is None else str(vessel.rssi))

        self.detail_callsign.setText(vessel.callsign or "-")
        self.detail_type.setText(vessel.type or "-")

        if vessel.range is not None:
            self.detail_range.setText(format_distance(vessel.range, self.settings.get("distance_unit", "NM")))
        else:
            self.detail_range.setText("-")

        if vessel.bearing is not None:
            self.detail_bearing.setText(f"{vessel.bearing:.0f}°")
        else:
            self.detail_bearing.setText("-")

        self.detail_seen.setText(self.format_seen(vessel))

        self.detail_destination.setText(vessel.destination or "-")

        self.detail_draught.setText("-" if vessel.draught is None else f"{vessel.draught:.1f} m")
        self.detail_imo.setText("-" if vessel.imo is None else str(vessel.imo))
        self.detail_rot.setText("-" if vessel.rot is None else f"{vessel.rot:.0f}°/min")
        self.detail_length.setText("-" if vessel.length is None else f"{vessel.length} m")
        self.detail_beam.setText("-" if vessel.beam is None else f"{vessel.beam} m")

    def reset_session(self):

        # Pinned vessels survive a clear, but with their data wiped back to
        # blank except for identity — they're placeholders ready to pick up
        # fresh data, not stale readings from the previous session.
        for mmsi, vessel in list(self.registry.vessels.items()):

            if vessel.pinned:
                self.reset_vessel_data(vessel)

            else:
                del self.registry.vessels[mmsi]

        self.target_tree.clear()

        self.tree_items.clear()

        self.last_ais_mmsi = None
        self.own_track = deque()

        # A fresh dict, not a mutation — self.own_position may still be the
        # same object GNSSParser handed back from process(), and reassigning
        # (rather than clearing it in place) avoids any risk of stepping on
        # that. Without this, a GNSS fix from before Clear/a replay-file-load
        # kept being reported as the current position (see record_own_position)
        # until the next real fix happened to arrive.
        self.own_position = {"lat": None, "lon": None, "fix": False}

        # The previously-selected vessel may no longer exist after this
        # reset (registry entries are wiped except pinned ones) — clearing
        # this alongside the detail panel keeps them in sync, matching
        # check_vessel_timeouts() below.
        self.selected_mmsi = None

        self.clear_vessel_details()

        self.update_target_tree()

    def clear_vessel_details(self):

        self.detail_mmsi.setText("-")
        self.detail_name.setText("-")
        self.detail_callsign.setText("-")
        self.detail_type.setText("-")
        self.detail_position.setText("-")
        self.detail_sog.setText("-")
        self.detail_cog.setText("-")
        self.detail_heading.setText("-")
        self.detail_nav_status.setText("-")
        self.detail_range.setText("-")
        self.detail_bearing.setText("-")
        self.detail_rssi.setText("-")
        self.detail_seen.setText("-")

        self.detail_destination.setText("-")
        self.detail_draught.setText("-")
        self.detail_imo.setText("-")
        self.detail_rot.setText("-")
        self.detail_length.setText("-")
        self.detail_beam.setText("-")

    def reset_vessel_data(self, vessel):

        mmsi = vessel.mmsi
        name = vessel.name

        del self.registry.vessels[mmsi]

        fresh = self.registry.get_or_create(mmsi)

        fresh.name = name
        fresh.pinned = True

        # Vessel.last_seen defaults to real wall-clock time (see
        # models/vessel.py), but during replay every other "Seen" age is
        # computed against self.replay.current_time — a simulated clock
        # that can be months away from the real one. Without this, a
        # pinned vessel survives Clear only to immediately show a bogus
        # Seen value (a huge, wrapped-looking number) until its next
        # actual report corrects it. Same live-vs-replay fallback already
        # used in parsers/ais_parser.py.
        fresh.last_seen = self.replay.current_time or datetime.now()

    def check_vessel_timeouts(self):

        if self.replay.current_time is None:
            return

        timeout_setting = self.settings.get("vessel_timeout", "10")

        if timeout_setting == "Unlimited":
            return

        timeout_seconds = int(timeout_setting) * 60

        expired = []

        for mmsi, vessel in self.registry.vessels.items():

            if vessel.pinned:
                continue

            age = (self.replay.current_time - vessel.last_seen).total_seconds()

            if age > timeout_seconds:
                expired.append(mmsi)

        for mmsi in expired:
            del self.registry.vessels[mmsi]

        # Otherwise the details panel keeps showing the timed-out vessel's
        # last values forever — update_target_tree()'s selected-vessel
        # refresh (below) finds nothing in the registry for a stale
        # selected_mmsi and just no-ops, leaving the last-rendered text in
        # place with no corresponding tree row selected.
        if self.selected_mmsi in expired:
            self.selected_mmsi = None
            self.clear_vessel_details()

    def trim_vessel_tracks(self):

        if self.replay.current_time is None:
            return

        track_length_setting = self.settings.get("track_length", "10")

        if track_length_setting == "Unlimited":
            return

        track_seconds = int(track_length_setting) * 60

        for vessel in self.registry.vessels.values():
            self.trim_track(vessel.track, track_seconds)

    def trim_own_track(self):

        if self.replay.current_time is None:
            return

        track_length_setting = self.settings.get("track_length", "10")

        if track_length_setting == "Unlimited":
            return

        track_seconds = int(track_length_setting) * 60

        self.trim_track(self.own_track, track_seconds)

    def trim_track(self, track, track_seconds):

        # Points are always appended in chronological order, so the stale
        # ones are always a run at the front — popleft() them off directly
        # (O(1) each on a deque) instead of rebuilding the whole track by
        # rescanning every point on every call, which made trim cost scale
        # with total track length instead of with how much is actually
        # stale since the last trim (measured: 93M+ total_seconds() calls
        # replaying a single field log with the old rebuild-every-time
        # approach, once tracks grew into the thousands of points).
        while track and (self.replay.current_time - track[0][0]).total_seconds() > track_seconds:
            track.popleft()
