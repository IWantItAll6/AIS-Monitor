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
    QLineEdit,
    QProgressDialog,
    QMenu
)

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QIcon, QCursor, QAction, QKeySequence, QActionGroup
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
import time

from services.range_limit import range_limit_nm, within_range_limit

from ui.communications_dialog import CommunicationsDialog
from ui.preferences_dialog import PreferencesDialog
from ui.help_dialog import HelpDialog
from ui.about_dialog import AboutDialog
from ui.error_log_dialog import ErrorLogDialog
from ui.file_analysis_dialog import FileAnalysisDialog
from services.file_analysis_service import FileAnalysisThread, extract_rssi_history
from services.error_log import ErrorLog
from services.settings_service import SettingsService
from services.vessel_registry import VesselRegistry
from parsers.ais_parser import AISParser
from parsers.gnss_parser import GNSSParser
from parsers.psmt_parser import PSMTParser
from services.geo import calculate_range_bearing, format_distance, convert_distance
from ui.vessel_tree_item import VesselTreeItem
from services.replay_service import ReplayService, extract_sentence
from ui.map_panel import MapPanel
from ui.rssi_graph import RssiGraphWidget, MARKER_SHAPES
from ui.vessel_uptime_bar import VesselUptimeBar
from ui.time_format import format_duration_short
from services.theme_service import apply_theme, apply_title_bar_theme
from services.serial_reader import SerialReaderThread
from services.network_reader import NetworkAisReader
from services.session_recorder import SessionRecorder
from services.broadcast_server import BroadcastServer


class MainWindow(QMainWindow):

    # How long the accelerated "show where things came from" preroll
    # animation takes in wall-clock time when landing on a scrubbed
    # position, regardless of how much simulated time it covers.
    SCRUB_ANIMATION_MS = 2500

    # Longest replay_next_line() keeps catching up on overdue batches in one
    # timer tick before yielding to the event loop (see there) — bigger
    # means more throughput at high speeds, smaller means smoother repaints
    # and snappier input while playback is behind.
    REPLAY_TICK_BUDGET_S = 0.1

    # RSSI graph / Vessel Uptime bar zoom (see adjust_graph_zoom) — a live,
    # session-only view preference, not persisted (same as the map's own
    # zoom level). Multiplicative step, not additive, so it feels like an
    # equal "amount" of zoom at any scale, same as the map's ZOOM_FACTOR.
    GRAPH_ZOOM_STEP = 1.5
    MIN_GRAPH_ZOOM_SECONDS = 30
    DEFAULT_GRAPH_ZOOM_SECONDS = 600  # first zoom-in step when track_length is Unlimited (no window to start from)

    # With Track Length or Vessel Timeout set to "Unlimited", seek_to_index()
    # has no bounded window to rewind by and must replay the whole file for
    # every scrub (see scrub_rewind_seconds) — measured on a real ~2hr/127k
    # -line trial log at ~1,350 lines/sec through the live processing path,
    # so this many lines implies a scrub could take upwards of ~15s. Past
    # that, a loaded file gets a one-time heads-up rather than the user
    # discovering it the slow way on their first scrub.
    LARGE_FILE_LINE_THRESHOLD = 20000

    # How often (in simulated replay time, not wall-clock) to force an
    # uptime tick during a bulk fast-forward — see tick_vessel_uptime_if_due.
    # A compromise: fine enough that even a fast vessel's grace window
    # (Class A at speed: 10s nominal * GRACE_MULTIPLIER = 20s) gets at
    # least one intermediate tick rather than none at all, without ticking
    # on literally every line of a dense fast-forward.
    BULK_TICK_INTERVAL_SECONDS = 15

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

        self.broadcast_client_count = 0
        self.broadcast_server = BroadcastServer()
        self.broadcast_server.client_count_changed.connect(self.on_broadcast_client_count_changed)

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

        # Set once an !AIVDO sentence (own-ship's echoed position report,
        # as opposed to !AIVDM for everyone else's) is seen — lets
        # MapPanel recolor that one registry entry to match the dedicated
        # own-ship icon instead of an ordinary vessel color.
        self.own_mmsi = None

        # None = showing the full track-length window (unzoomed); otherwise
        # the currently displayed width in seconds for the RSSI graph and
        # Vessel Uptime bar, which zoom together — see adjust_graph_zoom.
        self.graph_zoom_seconds = None

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

        # None outside a bulk fast-forward (Skip to End, a scrub's silent
        # catch-up) — see begin_bulk_replay()/end_bulk_replay().
        self._raw_data_buffer = None

        # Set by tick_vessel_uptime() every time it actually runs — read by
        # tick_vessel_uptime_if_due() during a bulk fast-forward to decide
        # whether enough simulated time has passed to force another tick.
        self._last_uptime_tick_time = None

        self.last_ais_mmsi = None

        self.seen_timer = QTimer()

        self.seen_timer.timeout.connect(self.update_target_tree)

        self.seen_timer.start(1000)

        self.scrub_timer = QTimer()

        self.scrub_timer.timeout.connect(self.scrub_animation_step)

        self._scrub_target_index = None
        self._scrub_lines_per_frame = 1

        self.apply_broadcast_settings()

    def create_collapsible_section(self, title, widget, setting_key, default_visible=True, extra_header_widget=None):
        """A titled section that can be quickly collapsed via an inline
        "►/▼ Title" button — the same collapse pattern already used for
        Raw Data — while (unlike Raw Data) remembering its shown/hidden
        state across restarts via settings[setting_key]. Returns
        (container, toggle_button, stats_label); the toggle is also handed
        back so callers can bidirectionally sync it with a View-menu
        action, the same way raw_toggle syncs with show_raw_data_action.
        stats_label sits right-aligned in the same header row (e.g. an
        uptime % or RSSI min/max/avg) so it's visible without spending
        extra vertical space, and stays visible even while collapsed.
        extra_header_widget, when given, sits between the toggle and the
        stats label — e.g. the shared graph-zoom controls, to avoid them
        costing their own row (see setup_ui)."""

        container = QWidget()

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        container.setLayout(layout)

        visible = self.settings.get(setting_key, default_visible)

        toggle = QPushButton(("▼ " if visible else "► ") + title)
        toggle.setCheckable(True)
        toggle.setChecked(visible)

        stats_label = QLabel("")
        stats_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(toggle)

        if extra_header_widget is not None:
            header_layout.addWidget(extra_header_widget)

        header_layout.addStretch()
        header_layout.addWidget(stats_label)

        layout.addLayout(header_layout)

        widget.setVisible(visible)
        layout.addWidget(widget)

        def on_toggled(checked):

            toggle.setText(("▼ " if checked else "► ") + title)
            widget.setVisible(checked)

            self.settings[setting_key] = checked

            SettingsService.save(self.settings)

        toggle.toggled.connect(on_toggled)

        return container, toggle, stats_label

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
        self.map_view.set_daylight_mode(self.settings.get("map_daylight_mode", False))
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

            # Selectable/copyable — a plain QLabel's text can't be selected
            # by default, which meant e.g. Position had to be retyped by
            # hand instead of copy-pasted (found by the user needing to do
            # exactly that with a lat/lon).
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

            details_layout.addWidget(caption_label, row, col)
            details_layout.addWidget(value_label, row, col + 1)

            self.detail_field_captions[name] = caption_label

        target_layout.addWidget(details_widget)

        self.rssi_graph = RssiGraphWidget()
        self.rssi_graph.set_vessel_color(self.settings["vessel_color"])
        self.rssi_graph.set_pinned_color(self.settings["pinned_color"])

        # Shared by the RSSI graph and Vessel Uptime bar below — scroll
        # over either graph also works (see their zoom_requested signals,
        # connected below once both widgets exist), this is just the
        # discoverable/precise alternative, same as the map's zoom buttons.
        # Sits inline in the RSSI History header (via extra_header_widget)
        # rather than its own row, to not cost extra vertical space in an
        # already-tall detail panel.
        zoom_controls = QWidget()

        zoom_layout = QHBoxLayout()
        zoom_layout.setContentsMargins(0, 0, 0, 0)
        zoom_controls.setLayout(zoom_layout)

        self.graph_zoom_out_button = QPushButton("-")
        self.graph_zoom_out_button.setMaximumWidth(22)
        self.graph_zoom_out_button.setToolTip("Zoom out (show more history)")
        zoom_layout.addWidget(self.graph_zoom_out_button)

        self.graph_zoom_label = QLabel("")
        self.graph_zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.graph_zoom_label.setMinimumWidth(32)
        zoom_layout.addWidget(self.graph_zoom_label)

        self.graph_zoom_in_button = QPushButton("+")
        self.graph_zoom_in_button.setMaximumWidth(22)
        self.graph_zoom_in_button.setToolTip("Zoom in (show less history)")
        zoom_layout.addWidget(self.graph_zoom_in_button)

        self.graph_zoom_reset_button = QPushButton("Reset")
        self.graph_zoom_reset_button.setMaximumWidth(48)
        zoom_layout.addWidget(self.graph_zoom_reset_button)

        self.export_rssi_button = QPushButton("Export")
        self.export_rssi_button.setMaximumWidth(54)
        self.export_rssi_button.setEnabled(False)

        export_rssi_menu = QMenu(self.export_rssi_button)
        export_rssi_menu.addAction("Image (PNG)...", self.export_rssi_png)
        export_rssi_menu.addAction("Data (CSV)...", self.export_rssi_csv)
        self.export_rssi_button.setMenu(export_rssi_menu)

        zoom_layout.addWidget(self.export_rssi_button)

        rssi_container, self.rssi_toggle, self.rssi_stats_label = self.create_collapsible_section(
            "RSSI History", self.rssi_graph, "show_rssi_graph", extra_header_widget=zoom_controls
        )
        target_layout.addWidget(rssi_container)

        self.uptime_bar = VesselUptimeBar()

        uptime_container, self.uptime_toggle, self.uptime_stats_label = self.create_collapsible_section(
            "Vessel Uptime", self.uptime_bar, "show_vessel_uptime"
        )
        target_layout.addWidget(uptime_container)

        self.graph_zoom_out_button.clicked.connect(lambda: self.adjust_graph_zoom(self.GRAPH_ZOOM_STEP))
        self.graph_zoom_in_button.clicked.connect(lambda: self.adjust_graph_zoom(1 / self.GRAPH_ZOOM_STEP))
        self.graph_zoom_reset_button.clicked.connect(self.reset_graph_zoom)

        self.rssi_graph.zoom_requested.connect(self.on_graph_zoom_wheel)
        self.uptime_bar.zoom_requested.connect(self.on_graph_zoom_wheel)

        self.rssi_toggle.toggled.connect(self.update_rssi_export_enabled)

        self.update_graph_zoom_label()

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
            self.communications_action.setEnabled(True)

            # Wall time spent stopped/paused/seeking mustn't count as elapsed
            # replay time — replay_next_line() re-anchors the clock on the
            # first batch it plays from here.
            self.replay.clear_clock()

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

            # Communications settings can't take effect against an
            # already-running reader (see MainWindow.show_communications) —
            # disabled here rather than left silently ineffective.
            self.communications_action.setEnabled(False)

            self.start_live_serial()

        self.start_action.setEnabled(False)
        self.pause_action.setEnabled(True)
        self.stop_action.setEnabled(True)

        self.update_status()

    def start_live_serial(self):

        self.recorder.start()
        self.warn_if_recordings_folder_large()

        self.serial_readers = [self.make_ais_reader()]

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

    def make_ais_reader(self):

        # Serial and Network are mutually exclusive AIS input sources (see
        # CommunicationsDialog) — never both readers running at once for
        # AIS, unlike GNSS which is a separate, always-serial concern.
        if self.settings.get("ais_source_type") == "Network":

            reader = NetworkAisReader(
                self.settings.get("ais_network_host", ""),
                int(self.settings.get("ais_network_port", "10110"))
            )

            reader.line_received.connect(self.on_live_line_received)
            reader.error_occurred.connect(self.on_serial_error)

            return reader

        return self.make_serial_reader("ais")

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

        # The bare sentence, not the "[timestamp] ..." wrapper above — that
        # wrapper is this app's own recording/replay format, while a
        # connected TCP client (OpenCPN, a companion app, etc.) expects a
        # plain NMEA/PSMT sentence as it would come off a real receiver.
        self.broadcast_server.broadcast_line(line)

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
        self.communications_action.setEnabled(True)

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
        self.communications_action.setEnabled(True)

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

        self.reschedule_replay_timer()

    def slower_clicked(self):

        self.replay.slow_down()

        self.speed_label.setText(f"{self.replay.speed}x")

        self.reschedule_replay_timer()

    def reschedule_replay_timer(self):

        # A wait already pending was computed at the old speed — without
        # this, a speed change mid-playback wouldn't take effect until that
        # (possibly long, e.g. a quiet gap at 1x) wait finished.
        if self.replay_timer.isActive() and self.replay.has_next():
            self.replay_timer.start(self.replay.ms_until_next_due())

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

        tick_started = time.monotonic()

        while True:

            # A batch, not one line: several sentences sharing the exact
            # same embedded timestamp (as real receivers do emit) should
            # play back together, not be spread out one-per-tick.
            for line in self.replay.next_batch():
                self.process_sentence(line)

            if self.replay.clock_time() is None:
                self.replay.anchor_clock()

            # Keep playing every batch the replay clock has already passed
            # (see ReplayService.anchor_clock) — this is what lets 2x/10x
            # actually run at 2x/10x when processing plus repainting can't
            # keep up with one batch per timer tick. Capped per tick so a
            # long catch-up still hands control back to the event loop to
            # repaint and handle input; the 1ms reschedule below carries on.
            if not self.replay.next_batch_due():
                break

            if time.monotonic() - tick_started > self.REPLAY_TICK_BUDGET_S:
                break

        self.replay_scrubber.setValue(self.replay.index)

        self.raw_data.verticalScrollBar().setValue(self.raw_data.verticalScrollBar().maximum())

        if self.replay.has_next():
            self.replay_timer.start(self.replay.ms_until_next_due())

        else:
            # Nothing left to time a wait against — let the next tick
            # (fired essentially immediately) hit the has_next() guard
            # above and stop cleanly.
            self.replay_timer.start(1)

    def process_sentence(self, line):

        sentence = extract_sentence(line)

        # Filtering only affects what's shown here — nothing about what
        # gets processed or (once session recording exists) logged to disk.
        if self.should_display_sentence(sentence):

            if self._raw_data_buffer is not None:
                self._raw_data_buffer.append(line)
            else:
                self.raw_data.append(line)

        timestamp = self.replay.update_time(line)

        # During a bulk fast-forward this is applied once, at the end (see
        # end_bulk_replay), instead of on every line — a real cost (a
        # strftime call plus a Qt label repaint) for a value nothing can
        # actually see change until the loop finishes anyway.
        if timestamp and hasattr(self, "replay_time_label") and self._raw_data_buffer is None:
            self.replay_time_label.setText(timestamp.strftime("%Y-%m-%d %H:%M:%S"))

        # Only actually needed during a bulk fast-forward (see
        # tick_vessel_uptime_if_due's docstring) — outside one, the
        # real-time seen_timer already ticks every second regardless of
        # traffic, so this would just be redundant, harmless extra work.
        if self._raw_data_buffer is not None:
            self.tick_vessel_uptime_if_due()

        self.route_sentence(sentence)

    def begin_bulk_replay(self):
        """Call before a tight, unpaced fast-forward loop over many lines
        (Skip to End, a scrub's silent catch-up) — suppresses process_sentence's
        per-line Raw Data append and replay-time label update, both real
        costs (profiled: ~2s combined over a 100k-line real capture) for
        state nothing can actually see mid-loop, applying the final result
        in one shot via end_bulk_replay() instead. Purely a performance
        measure — every line's raw text still ends up in Raw Data, just
        appended in one batch rather than one Qt call per line.

        Also arms tick_vessel_uptime_if_due()'s periodic ticking for the
        duration of the loop, which is a correctness fix, not a performance
        one — see its docstring."""

        self._raw_data_buffer = []
        self._last_uptime_tick_time = self.replay.current_time

    def end_bulk_replay(self):

        if self._raw_data_buffer:
            self.raw_data.append("\n".join(self._raw_data_buffer))

        self._raw_data_buffer = None

        if self.replay.current_time is not None and hasattr(self, "replay_time_label"):
            self.replay_time_label.setText(self.replay.current_time.strftime("%Y-%m-%d %H:%M:%S"))

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

                if self.replay.current_time is not None:
                    vessel.uptime_tracker.record_report(
                        self.replay.current_time,
                        self.ais_parser.last_msg_type,
                        self.ais_parser.last_cs,
                        vessel.sog,
                        vessel.nav_status,
                    )

                self.update_target_tree()

        elif sentence.startswith("!AIVDO"):

            # Own-ship's echoed position report — decode it like any other
            # vessel so its SOG/COG etc. are visible in the details panel,
            # but deliberately don't touch last_ais_mmsi: that's for
            # correlating $PSMT RSSI readings with a *received* transmission,
            # and our own outgoing one isn't that.
            vessel = self.ais_parser.process(sentence, self.replay.current_time)

            if vessel:
                self.own_mmsi = vessel.mmsi
                self.update_target_tree()

        elif sentence.startswith("$PSMT"):

            psmt = self.psmt_parser.process(sentence)

            if psmt and self.last_ais_mmsi is not None:

                vessel = self.registry.get(self.last_ais_mmsi)

                if vessel:
                    vessel.rssi = psmt["rssi"]

                    if self.replay.current_time is not None:
                        vessel.rssi_history.append((self.replay.current_time, psmt["rssi"]))

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

        # Sorting stays disabled for the whole bulk update below and a
        # single explicit resort is forced at the end — leaving it enabled
        # through the loop means every single setText()/setData() call
        # live-resorts the tree, and under busy traffic that resort can
        # re-enter itself until Qt/Python's recursion limit blows
        # (RecursionError in VesselTreeItem.__lt__). Re-enabling sorting
        # alone does *not* itself trigger a fresh resort against the data
        # this loop just changed (confirmed: a newly-pinned row's data
        # updated correctly but stayed at its old, pre-change position) —
        # sortItems() has to be called explicitly.
        self.target_tree.setSortingEnabled(False)

        try:
            self._update_target_tree()

        finally:
            self.target_tree.setSortingEnabled(True)

            sort_column = self.target_tree.sortColumn()

            if sort_column != -1:
                self.target_tree.sortItems(sort_column, self.target_tree.header().sortIndicatorOrder())

    def _update_target_tree(self):

        self.check_vessel_timeouts()
        self.trim_vessel_tracks()
        self.trim_vessel_rssi_history()
        self.trim_own_track()

        # Ticked here (not only on report arrival) so a vessel that's gone
        # quiet still progresses green -> amber -> red from elapsed time
        # alone — update_target_tree() already runs on both the 1s
        # seen_timer and every incoming AIS message, so this rides that
        # existing cadence rather than needing its own timer.
        self.tick_vessel_uptime()
        self.trim_vessel_uptime()

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

        # Ranges were just refreshed above, so this is the point to apply
        # the Range Limit — map and list both hide the same vessels.
        limit_nm = self.current_range_limit_nm()
        in_range = [v for v in self.registry.all() if within_range_limit(v, limit_nm)]

        total = len(self.registry.vessels)

        if len(in_range) < total:
            self.targets_label.setText(f"Targets ({len(in_range)} of {total})")
        else:
            self.targets_label.setText(f"Targets ({total})")

        self.map_view.update_vessels(in_range, self.own_position, self.own_track, self.own_mmsi)

        self.update_status()

        self.apply_target_filter()

        if self.selected_mmsi is not None:

            vessel = self.registry.get(self.selected_mmsi)

            if vessel:
                self.show_vessel_details(vessel)

    def current_range_limit_nm(self):

        return range_limit_nm(self.settings.get("range_limit", 60), self.settings.get("distance_unit", "NM"))

    def apply_target_filter(self):

        query = self.target_search.text().strip().lower()

        limit_nm = self.current_range_limit_nm()

        for mmsi, item in self.tree_items.items():

            vessel = self.registry.get(mmsi)

            if vessel is not None and not within_range_limit(vessel, limit_nm):
                item.setHidden(True)
                continue

            if not query:
                item.setHidden(False)
                continue

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

        if self.settings.get("broadcast_enabled"):
            message += f" | Broadcast: {self.broadcast_client_count} client(s)"

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

    def on_broadcast_client_count_changed(self, count):

        self.broadcast_client_count = count

        self.update_status()

    def apply_broadcast_settings(self):

        self.broadcast_server.stop()

        if self.settings.get("broadcast_enabled"):

            port = int(self.settings.get("broadcast_port", "10110"))

            if not self.broadcast_server.start(port):
                self.status_bar.showMessage(f"Broadcast: could not listen on port {port}", 5000)

        self.update_status()

    def closeEvent(self, event):

        self.stop_live_serial()

        self.broadcast_server.stop()

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
            self.apply_broadcast_settings()

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
            self.map_view.set_daylight_mode(self.settings["map_daylight_mode"])
            self.rssi_graph.set_vessel_color(self.settings["vessel_color"])
            self.rssi_graph.set_pinned_color(self.settings["pinned_color"])
            self.map_view.set_coastal_filter(
                self.settings["coastal_towns_only"], float(self.settings["coastal_threshold_nm"])
            )
            self.recorder.directory = Path(self.settings["recordings_folder"])

            # Apply a changed Range Limit (or distance unit, which it's
            # expressed in) right away rather than on the next message.
            self.update_target_tree()

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

        self.show_rssi_graph_action = view_menu.addAction("Show RSSI Graph")
        self.show_rssi_graph_action.setCheckable(True)
        self.show_rssi_graph_action.setChecked(self.settings.get("show_rssi_graph", True))
        self.show_rssi_graph_action.toggled.connect(self.rssi_toggle.setChecked)
        self.rssi_toggle.toggled.connect(self.show_rssi_graph_action.setChecked)

        self.show_vessel_uptime_action = view_menu.addAction("Show Vessel Uptime")
        self.show_vessel_uptime_action.setCheckable(True)
        self.show_vessel_uptime_action.setChecked(self.settings.get("show_vessel_uptime", True))
        self.show_vessel_uptime_action.toggled.connect(self.uptime_toggle.setChecked)
        self.uptime_toggle.toggled.connect(self.show_vessel_uptime_action.setChecked)

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

        file_menu.addSeparator()

        self.analyze_file_action = file_menu.addAction("Analyze File...")

        self.analyze_file_action.triggered.connect(self.run_file_analysis)

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

        self.setup_test_menu(view_menu)

    def setup_test_menu(self, view_menu):
        """Originally a throwaway "Test" menu for comparing three ways to
        indicate individual RSSI transmissions on RssiGraphWidget (per-gap
        markers, an endpoint-only marker, and axis ticks) without
        cluttering a fast-reporting vessel's line — a blanket "always show
        a cross" approach turned out too busy at high report rates (see
        git log). Kept under View since it settled into a real, persisted
        preference rather than a one-off comparison; still no keyboard
        shortcuts, still fair game to prune down to whichever combination
        wins out."""

        rssi_menu = view_menu.addMenu("RSSI Markers")

        self.rssi_point_markers_action = rssi_menu.addAction("Per-Gap Markers")
        self.rssi_point_markers_action.setCheckable(True)
        self.rssi_point_markers_action.setChecked(self.settings.get("rssi_marker_points", False))

        self.rssi_endpoint_marker_action = rssi_menu.addAction("Endpoint Marker")
        self.rssi_endpoint_marker_action.setCheckable(True)
        self.rssi_endpoint_marker_action.setChecked(self.settings.get("rssi_marker_endpoint", False))

        self.rssi_axis_ticks_action = rssi_menu.addAction("Axis Ticks")
        self.rssi_axis_ticks_action.setCheckable(True)
        self.rssi_axis_ticks_action.setChecked(self.settings.get("rssi_marker_axis_ticks", False))

        rssi_menu.addSeparator()

        shape_menu = rssi_menu.addMenu("Marker Shape")

        shape_group = QActionGroup(self)
        shape_group.setExclusive(True)

        saved_shape = self.settings.get("rssi_marker_shape", "circle")

        self.rssi_shape_actions = {}

        for shape in MARKER_SHAPES:

            action = shape_menu.addAction(shape.capitalize())
            action.setCheckable(True)
            action.setChecked(shape == saved_shape)

            shape_group.addAction(action)
            self.rssi_shape_actions[action] = shape

        for action in [
            self.rssi_point_markers_action,
            self.rssi_endpoint_marker_action,
            self.rssi_axis_ticks_action,
            *self.rssi_shape_actions,
        ]:
            action.triggered.connect(self.apply_rssi_marker_test_options)

        # Applied here (not left to wait for the first toggle) so a
        # previously-saved choice actually takes effect on launch.
        self.apply_rssi_marker_test_options()

    def apply_rssi_marker_test_options(self):

        shape = next((shape for action, shape in self.rssi_shape_actions.items() if action.isChecked()), "circle")

        self.settings["rssi_marker_points"] = self.rssi_point_markers_action.isChecked()
        self.settings["rssi_marker_endpoint"] = self.rssi_endpoint_marker_action.isChecked()
        self.settings["rssi_marker_axis_ticks"] = self.rssi_axis_ticks_action.isChecked()
        self.settings["rssi_marker_shape"] = shape

        SettingsService.save(self.settings)

        self.rssi_graph.set_marker_options(
            self.rssi_point_markers_action.isChecked(),
            self.rssi_endpoint_marker_action.isChecked(),
            self.rssi_axis_ticks_action.isChecked(),
            shape,
        )

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

    def run_file_analysis(self):

        start_dir = self.settings.get("last_replay_folder", "")

        filename, _ = QFileDialog.getOpenFileName(
            self, "Analyze File", start_dir, "Log Files (*.txt *.log);;All Files (*)"
        )

        if not filename:
            return

        self.settings["last_replay_folder"] = str(Path(filename).parent)

        SettingsService.save(self.settings)

        # A completely separate, untrimmed pass over the file — deliberately
        # NOT reading self.registry/self.replay, which are the live view's
        # continuously trimmed/timed-out state (see file_analysis_service's
        # own docstring for why that would silently produce wrong numbers).
        # Run on a background thread (see FileAnalysisThread) since a large
        # enough file — a multi-day continuous capture — can take upwards
        # of 30s, long enough to freeze the UI if run inline here.
        self.analysis_thread = FileAnalysisThread(filename)

        progress_dialog = QProgressDialog("Analyzing file...", "Cancel", 0, 100, self)
        progress_dialog.setWindowTitle("File Analysis")
        apply_title_bar_theme(progress_dialog, self.settings["theme"])
        progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setValue(0)

        self.analysis_thread.progress.connect(
            lambda done, total: progress_dialog.setValue(int(done / total * 100) if total else 100)
        )
        progress_dialog.canceled.connect(self.analysis_thread.cancel)

        def on_analysis_finished(analyses):

            progress_dialog.close()

            if not analyses:
                QMessageBox.information(self, "File Analysis", "No AIS targets found in this file.")
                return

            dialog = FileAnalysisDialog(filename, analyses, self.settings.get("distance_unit", "NM"))
            apply_title_bar_theme(dialog, self.settings["theme"])
            dialog.exec()

        def on_analysis_failed(message):

            progress_dialog.close()

            QMessageBox.warning(self, "File Analysis", f"Could not analyze file: {message}")

        self.analysis_thread.finished_analysis.connect(on_analysis_finished)
        self.analysis_thread.cancelled.connect(progress_dialog.close)
        self.analysis_thread.failed.connect(on_analysis_failed)

        self.analysis_thread.start()

        # Blocks this method (not the whole app) in a local event loop until
        # progress_dialog.close() is called above — the analysis itself
        # keeps running on analysis_thread, which is what keeps the rest of
        # the app's event loop (and this dialog's own Cancel button)
        # responsive throughout.
        progress_dialog.exec()

        # A signal (finished_analysis/cancelled/failed) firing only means
        # analysis_thread is about to return from run(), not that it has —
        # confirmed empirically: right after a cancel, isRunning() was still
        # True here without this wait(). The success path happened to mask
        # this (opening FileAnalysisDialog gave the thread plenty of time to
        # actually finish first), but cancel/fail return almost immediately,
        # risking the same "QThread: Destroyed while thread is still
        # running" class of bug already hit once in stop_live_serial().
        self.analysis_thread.wait()

    def load_replay_file(self, filename):

        self.reset_session()

        self.replay.load_file(filename)

        self.warn_if_unbounded_scrub_on_large_file()

        self.replay.filename = filename
        self.replay.reset()
        self.current_mode = "Replay"
        self.communications_action.setEnabled(True)
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
        # per-message UI rendering. begin_bulk_replay() strips out the
        # other big avoidable cost, per-line Raw Data/time-label updates.
        self.begin_bulk_replay()

        while self.replay.has_next():

            line = self.replay.next_line()

            self.process_sentence(line)

        self.end_bulk_replay()

        self.replay_scrubber.setValue(self.replay.index)

        self.current_mode = "Stopped"
        self.communications_action.setEnabled(True)

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

    def scrub_rewind_seconds(self):
        """How far back a scrub needs to replay from to correctly
        reconstruct app state at the target — the wider of Track Length
        (how much track/RSSI history should end up visible) and Vessel
        Timeout (how long a quiet vessel stays in the list at all; if it's
        the larger of the two, rewinding by Track Length alone could land
        on a target where a vessel has silently dropped out of the list
        that continuous playback would have kept). None means unbounded —
        at least one of the two settings is "Unlimited", so there's no
        finite window to rewind by; the caller must replay from the start
        of the file instead."""

        track_setting = self.settings.get("track_length", "10")
        timeout_setting = self.settings.get("vessel_timeout", "10")

        if track_setting == "Unlimited" or timeout_setting == "Unlimited":
            return None

        return max(int(track_setting), int(timeout_setting)) * 60

    def estimated_worst_case_scrub_lines(self):
        """How many lines a single scrub might need to replay in the worst
        case — an unbounded (Unlimited) setting means the whole file, but
        even a bounded window can still amount to a lot of lines on a
        dense-enough capture (e.g. a 60-minute Track Length on a busy
        file), so this is estimated from the file's own average line
        density (lines per second, from its first to last timestamp)
        rather than just checking for "Unlimited" — what actually
        determines scrub cost is how many lines fall inside the rewind
        window, not whether that window happens to be finite."""

        total_lines = len(self.replay.lines)

        if total_lines == 0:
            return 0

        rewind_seconds = self.scrub_rewind_seconds()

        if rewind_seconds is None:
            return total_lines

        first_time = next(
            (t for line in self.replay.lines if (t := self.replay.extract_timestamp(line.rstrip())) is not None),
            None
        )
        last_time = next(
            (
                t for line in reversed(self.replay.lines)
                if (t := self.replay.extract_timestamp(line.rstrip())) is not None
            ),
            None
        )

        if first_time is None or last_time is None or last_time <= first_time:
            return total_lines

        lines_per_second = total_lines / (last_time - first_time).total_seconds()

        return int(lines_per_second * rewind_seconds)

    def warn_if_unbounded_scrub_on_large_file(self):

        estimated_lines = self.estimated_worst_case_scrub_lines()

        if estimated_lines < self.LARGE_FILE_LINE_THRESHOLD:
            return

        if self.scrub_rewind_seconds() is None:
            reason = "Track Length and/or Vessel Timeout is set to \"Unlimited\", so there's no bounded window " \
                     "to rewind by — every scrub has to replay the file from the start."
        else:
            reason = (
                f"Your Track Length/Vessel Timeout settings and this file's message density mean a single "
                f"scrub could still need to replay roughly {estimated_lines:,} lines."
            )

        QMessageBox.information(
            self, "Large File, Slow Scrubbing Likely",
            f"{reason}\n\nA shorter Track Length/Vessel Timeout in Preferences will make scrubbing faster."
        )

    def seek_to_index(self, target_index):

        if not self.replay.filename or not self.replay.lines:
            return

        target_index = max(0, min(target_index, len(self.replay.lines) - 1))

        target_time = self.replay.extract_timestamp(self.replay.lines[target_index])

        self.reset_session()

        rewind_seconds = self.scrub_rewind_seconds()

        # Rewind only as far as still guarantees a correct reconstruction
        # at the target, instead of always replaying from the start of the
        # file — on a real ~2hr/127k-line trial log, scrubbing near the end
        # with a 10-minute window measured ~22x faster than the old
        # always-from-zero approach (93.6s -> 4.3s). Unbounded settings (see
        # scrub_rewind_seconds) still fall back to replaying everything.
        rewind_start_index = 0

        if target_time is not None and rewind_seconds is not None:

            rewind_start_time = target_time - timedelta(seconds=rewind_seconds)

            for i in range(target_index + 1):

                line_time = self.replay.extract_timestamp(self.replay.lines[i])

                # An unparseable line (e.g. a blank leading line before the
                # file's first real entry) isn't necessarily at/after the
                # boundary — skip over it rather than stopping the scan
                # there, or a single early bad line would defeat the whole
                # rewind (confirmed: a real trial log opens with exactly
                # one blank line and this silently fell back to a full
                # from-zero replay on every scrub before this fix).
                if line_time is None:
                    continue

                if line_time < rewind_start_time:
                    rewind_start_index = i + 1

                else:
                    break

        self.replay.reset()
        self.replay.index = rewind_start_index

        # Default: no animation, process straight through the target line
        # (inclusive) in the instant/silent loop below.
        preroll_start_index = target_index + 1

        track_setting = self.settings.get("track_length", "10")

        # "Unlimited" has no finite window to rewind by — fall back to an
        # instant landing rather than silently inventing an arbitrary
        # duration the user never configured.
        if self.animate_scrub_checkbox.isChecked() and target_time is not None and track_setting != "Unlimited":

            window_start = target_time - timedelta(minutes=int(track_setting))

            preroll_start_index = rewind_start_index

            for i in range(rewind_start_index, target_index + 1):

                line_time = self.replay.extract_timestamp(self.replay.lines[i])

                if line_time is None:
                    continue

                if line_time < window_start:
                    preroll_start_index = i + 1

                else:
                    break

            preroll_start_index = min(preroll_start_index, target_index)

        # Silently fast-forward (no timer pacing, same technique as Skip to
        # End) up to the start of the animated window — or straight to the
        # target if not animating. This is a synchronous re-simulation from
        # rewind_start_index (ReplayService has no true random-access seek),
        # which — especially with Unlimited settings forcing a from-the-start
        # replay — can still take a while on a large capture. The wait
        # cursor plus periodic processEvents() below only keep the window
        # responsive/repainting during that time, they don't make it faster.
        # The scrubber/Skip to End are disabled for the duration so
        # processEvents() can't let the user fire a second, overlapping seek
        # into this same synchronous loop.
        self.begin_bulk_replay()

        self.replay_scrubber.setEnabled(False)
        self.skip_to_end_action.setEnabled(False)

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        try:
            processed = 0

            while self.replay.index < preroll_start_index:
                self.process_sentence(self.replay.next_line())

                processed += 1

                if processed % 500 == 0:
                    QApplication.processEvents()

        finally:
            QApplication.restoreOverrideCursor()
            self.replay_scrubber.setEnabled(True)
            self.skip_to_end_action.setEnabled(True)

        self.end_bulk_replay()

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
        self.communications_action.setEnabled(True)

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
        self.communications_action.setEnabled(True)

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

        window_start = (
            self.graph_window_start(self.replay.current_time) if self.replay.current_time is not None else None
        )

        self.rssi_graph.set_history(vessel.rssi_history, self.replay.current_time, vessel.pinned, window_start)

        visible_rssi_history = (
            [(t, r) for t, r in vessel.rssi_history if t >= window_start]
            if window_start is not None else list(vessel.rssi_history)
        )
        rssi_stats = RssiGraphWidget.compute_stats(visible_rssi_history)
        self.rssi_stats_label.setText(self.format_rssi_stats(rssi_stats))

        self.update_rssi_export_enabled()

        if self.replay.current_time is not None:

            self.uptime_bar.set_segments(
                vessel.uptime_tracker.segments(self.replay.current_time), self.replay.current_time, window_start
            )

            uptime_pct = vessel.uptime_tracker.uptime_percentage(self.replay.current_time, window_start)
            self.uptime_stats_label.setText(self.format_uptime_stats(uptime_pct))

        else:
            self.uptime_bar.clear()
            self.uptime_stats_label.setText("")

    def format_rssi_stats(self, stats):

        if stats is None:
            return ""

        rssi_min, rssi_max, rssi_avg = stats

        return f"min {rssi_min} · avg {rssi_avg:.0f} · max {rssi_max} dBm"

    def format_uptime_stats(self, uptime_pct):

        if uptime_pct is None:
            return ""

        return f"{uptime_pct:.0f}% up"

    def update_rssi_export_enabled(self):

        vessel = self.registry.get(self.selected_mmsi) if self.selected_mmsi is not None else None

        self.export_rssi_button.setEnabled(
            vessel is not None and bool(vessel.rssi_history) and self.rssi_toggle.isChecked()
        )

    def export_rssi_png(self):

        filename, _ = QFileDialog.getSaveFileName(
            self, "Export RSSI Graph Image", "rssi_graph.png", "PNG Image (*.png)"
        )

        if not filename:
            return

        # Whatever's currently on screen — zoom window included, same as a
        # real screenshot would capture.
        self.rssi_graph.grab().save(filename, "PNG")

        self.status_bar.showMessage(f"RSSI graph image exported to {filename}", 5000)

    def prompt_rssi_export_scope(self, full_label):
        """Returns "current", "full", or None (cancelled) — split out from
        export_rssi_csv() so tests can drive the choice directly instead of
        simulating a real QMessageBox click."""

        box = QMessageBox(self)
        box.setWindowTitle("Export RSSI Data")
        box.setText("Export which RSSI data?")

        current_view_button = box.addButton("Current View", QMessageBox.ButtonRole.AcceptRole)
        full_button = box.addButton(full_label, QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)

        box.exec()

        clicked = box.clickedButton()

        if clicked == current_view_button:
            return "current"

        if clicked == full_button:
            return "full"

        return None

    def export_rssi_csv(self):

        vessel = self.registry.get(self.selected_mmsi) if self.selected_mmsi is not None else None

        if vessel is None:
            return

        # "Full File" only means something with a loaded replay log to
        # re-scan — Live mode has no bounded file, just whatever's still
        # retained.
        full_label = "Full File" if self.replay.filename else "Full Retained History"

        scope = self.prompt_rssi_export_scope(full_label)

        if scope == "current":

            window_start = (
                self.graph_window_start(self.replay.current_time) if self.replay.current_time is not None else None
            )

            history = (
                [(t, r) for t, r in vessel.rssi_history if t >= window_start]
                if window_start is not None else list(vessel.rssi_history)
            )

        elif scope == "full":

            history = (
                extract_rssi_history(self.replay.lines, self.selected_mmsi)
                if self.replay.filename else list(vessel.rssi_history)
            )

        else:
            return

        filename, _ = QFileDialog.getSaveFileName(
            self, "Export RSSI Data as CSV", "rssi_history.csv", "CSV File (*.csv)"
        )

        if not filename:
            return

        import csv

        with open(filename, "w", newline="", encoding="utf-8") as f:

            writer = csv.writer(f)
            writer.writerow(["Timestamp", "RSSI (dBm)"])

            for timestamp, rssi in history:
                writer.writerow([timestamp.strftime("%Y-%m-%d %H:%M:%S.%f") if timestamp else "", rssi])

        self.status_bar.showMessage(f"RSSI data exported to {filename}", 5000)

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
        self.own_mmsi = None

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

        self.rssi_graph.clear()
        self.rssi_stats_label.setText("")

        self.uptime_bar.clear()
        self.uptime_stats_label.setText("")

        self.update_rssi_export_enabled()

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
        expired_labels = {}

        for mmsi, vessel in self.registry.vessels.items():

            if vessel.pinned:
                continue

            age = (self.replay.current_time - vessel.last_seen).total_seconds()

            if age > timeout_seconds:
                expired.append(mmsi)
                expired_labels[mmsi] = vessel.name or str(mmsi)

        for mmsi in expired:
            del self.registry.vessels[mmsi]

        # Otherwise the details panel keeps showing the timed-out vessel's
        # last values forever — update_target_tree()'s selected-vessel
        # refresh (below) finds nothing in the registry for a stale
        # selected_mmsi and just no-ops, leaving the last-rendered text in
        # place with no corresponding tree row selected. Surfaced via the
        # status bar (not just silently blanked) — otherwise this reads as
        # the detail panel and its graphs randomly going blank for no
        # visible reason, most confusing near the end of a long replay
        # where it's easy to not have noticed the exact moment it happened.
        if self.selected_mmsi in expired:

            label = expired_labels[self.selected_mmsi]

            self.selected_mmsi = None
            self.clear_vessel_details()

            self.status_bar.showMessage(
                f"{label} removed from targets — no data for over {timeout_setting} min", 8000
            )

    def trim_vessel_tracks(self):

        if self.replay.current_time is None:
            return

        track_length_setting = self.settings.get("track_length", "10")

        if track_length_setting == "Unlimited":
            return

        track_seconds = int(track_length_setting) * 60

        for vessel in self.registry.vessels.values():
            self.trim_track(vessel.track, track_seconds)

    def trim_vessel_rssi_history(self):

        if self.replay.current_time is None:
            return

        track_length_setting = self.settings.get("track_length", "10")

        if track_length_setting == "Unlimited":
            return

        track_seconds = int(track_length_setting) * 60

        for vessel in self.registry.vessels.values():
            self.trim_track(vessel.rssi_history, track_seconds)

    def tick_vessel_uptime(self):

        if self.replay.current_time is None:
            return

        for vessel in self.registry.vessels.values():
            vessel.uptime_tracker.tick(self.replay.current_time)

        self._last_uptime_tick_time = self.replay.current_time

    def tick_vessel_uptime_if_due(self):
        """Call after every line during a bulk fast-forward (see
        begin_bulk_replay) — without periodic ticking, a genuine outage
        spanning a stretch with no !AIVDM/!AIVDO/$PSMT traffic at all (only
        e.g. GNSS chatter) never gets an intermediate tick, since only
        those message types trigger update_target_tree()'s own
        tick_vessel_uptime() call. That collapses the whole outage's
        AMBER/RED transition timestamps to the exact instant of the
        resuming report — a zero-width, invisible segment on the uptime
        bar — instead of reflecting when the outage actually started.
        Outside a bulk fast-forward the real-time seen_timer already ticks
        every second regardless of traffic, so this isn't needed there."""

        if self.replay.current_time is None:
            return

        if self._last_uptime_tick_time is None:
            self.tick_vessel_uptime()
            return

        elapsed = (self.replay.current_time - self._last_uptime_tick_time).total_seconds()

        if elapsed >= self.BULK_TICK_INTERVAL_SECONDS:
            self.tick_vessel_uptime()

    def full_track_window_seconds(self):
        """None for "Unlimited" track length, else the configured window in
        seconds. Split out from track_window_start so adjust_graph_zoom can
        clamp the zoom level to it without duplicating the settings lookup."""

        track_length_setting = self.settings.get("track_length", "10")

        if track_length_setting == "Unlimited":
            return None

        return int(track_length_setting) * 60

    def track_window_start(self, now):
        """None for "Unlimited" track length, else `now` minus the
        configured window — used only for actual data retention
        (trim_vessel_uptime, trim_vessel_tracks, etc.), which must stay
        tied to the track length setting regardless of the live graph zoom
        level. For how much of that retained history is currently
        *displayed*, see graph_window_start instead."""

        full_seconds = self.full_track_window_seconds()

        if full_seconds is None:
            return None

        return now - timedelta(seconds=full_seconds)

    def graph_window_start(self, now):
        """Like track_window_start, but narrowed by the live zoom level
        (see adjust_graph_zoom) — this is what the RSSI graph and Vessel
        Uptime bar actually display, and track_window_start (unaffected by
        zoom) is still what bounds it: zooming in only shows less of the
        retained history, it never retains less."""

        full_start = self.track_window_start(now)

        if self.graph_zoom_seconds is None:
            return full_start

        zoomed_start = now - timedelta(seconds=self.graph_zoom_seconds)

        if full_start is not None:
            return max(zoomed_start, full_start)

        return zoomed_start

    def on_graph_zoom_wheel(self, direction):

        factor = (1 / self.GRAPH_ZOOM_STEP) if direction > 0 else self.GRAPH_ZOOM_STEP

        self.adjust_graph_zoom(factor)

    def adjust_graph_zoom(self, factor):
        """factor < 1 zooms in (shorter displayed window), factor > 1 zooms
        out (longer window, up to the full track-length setting — can't
        zoom out past what's actually retained). Snaps back to None (the
        unzoomed "full window" state) once zooming out would reach or
        exceed that full window anyway, so Reset isn't the only way back
        to it."""

        current_seconds = self.graph_zoom_seconds or self.full_track_window_seconds() or self.DEFAULT_GRAPH_ZOOM_SECONDS

        new_seconds = max(current_seconds * factor, self.MIN_GRAPH_ZOOM_SECONDS)

        full_seconds = self.full_track_window_seconds()

        if full_seconds is not None and new_seconds >= full_seconds:
            self.graph_zoom_seconds = None
        else:
            self.graph_zoom_seconds = new_seconds

        self.update_graph_zoom_label()
        self.refresh_selected_vessel_graphs()

    def reset_graph_zoom(self):

        self.graph_zoom_seconds = None

        self.update_graph_zoom_label()
        self.refresh_selected_vessel_graphs()

    def update_graph_zoom_label(self):

        if self.graph_zoom_seconds is not None:
            self.graph_zoom_label.setText(format_duration_short(self.graph_zoom_seconds))
            return

        full_seconds = self.full_track_window_seconds()

        self.graph_zoom_label.setText(format_duration_short(full_seconds) if full_seconds is not None else "Full")

    def refresh_selected_vessel_graphs(self):
        """Applies a new zoom level immediately rather than waiting for the
        next tick/message to happen to refresh the currently-selected
        vessel's graphs."""

        if self.selected_mmsi is None:
            return

        vessel = self.registry.get(self.selected_mmsi)

        if vessel:
            self.show_vessel_details(vessel)

    def trim_vessel_uptime(self):

        if self.replay.current_time is None:
            return

        cutoff = self.track_window_start(self.replay.current_time)

        if cutoff is None:
            return

        for vessel in self.registry.vessels.values():
            vessel.uptime_tracker.trim(cutoff)

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
