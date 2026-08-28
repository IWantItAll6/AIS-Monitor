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
    QProgressBar,
    QCheckBox,
    QSizePolicy,
    QApplication,
    QWidgetAction
)

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QIcon
import re
from collections import deque
from datetime import datetime

from ui.communications_dialog import CommunicationsDialog
from ui.preferences_dialog import PreferencesDialog
from ui.help_dialog import HelpDialog
from ui.about_dialog import AboutDialog
from services.settings_service import SettingsService
from services.vessel_registry import VesselRegistry
from parsers.ais_parser import AISParser
from parsers.gnss_parser import GNSSParser
from parsers.psmt_parser import PSMTParser
from services.geo import calculate_range_bearing, format_distance
from ui.vessel_tree_item import VesselTreeItem
from services.replay_service import ReplayService
from ui.map_panel import MapPanel
from services.theme_service import apply_theme, apply_title_bar_theme
from services.serial_reader import SerialReaderThread
from services.session_recorder import SessionRecorder


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.settings = SettingsService.load()

        apply_theme(QApplication.instance(), self.settings["theme"])
        apply_title_bar_theme(self, self.settings["theme"])

        self.current_mode = "Stopped"

        self.setWindowTitle("AIS Monitor")
        self.setWindowIcon(QIcon("assets/app_icon.png"))
        self.resize(1400, 900)

        self.replay = ReplayService()

        self.serial_readers = []
        self.recorder = SessionRecorder()

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

        self.ais_parser = AISParser(self.registry)
        self.gnss_parser = GNSSParser()
        self.psmt_parser = PSMTParser()

        self.setup_ui()

        self.create_toolbar()
        self.selected_mmsi = None
        self.replay_interval_ms = 100
        # self.add_test_targets()
        self.create_menu()
        self.replay_time = None
        self.replay.speed = 1
        self.current_interval_ms = self.replay_interval_ms

        self.target_tree.itemClicked.connect(self.on_vessel_selected)
        self.target_tree.itemDoubleClicked.connect(self.on_vessel_double_clicked)
        self.map_view.vessel_clicked.connect(self.on_map_vessel_clicked)
        self.map_view.vessel_double_clicked.connect(self.toggle_vessel_pin)
        self.exit_replay_action.triggered.connect(self.exit_replay)

        self.replay.filename = None

        self.replay_timer = QTimer()

        self.replay_timer.timeout.connect(self.replay_next_line)

        self.last_ais_mmsi = None

        self.seen_timer = QTimer()

        self.seen_timer.timeout.connect(self.update_target_tree)

        self.seen_timer.start(1000)

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QVBoxLayout()
        central.setLayout(root_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)

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
            "data/geonames/gb_towns.json",
            "data/naturalearth/ne_10m_rivers_lake_centerlines/ne_10m_rivers_lake_centerlines.shp"
        )

        self.map_view.set_distance_unit(self.settings["distance_unit"])

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

        self.target_tree = QTreeWidget()
        self.tree_items = {}
        self.target_tree.setHeaderLabels(["★", "MMSI", "Name", "Range", "Bearing", "RSSI", "Seen"])

        self.target_tree.setColumnWidth(0, 25)  # Star
        self.target_tree.setColumnWidth(1, 95)  # MMSI
        self.target_tree.setColumnWidth(3, 60)  # Range
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

        # Left side

        self.detail_mmsi = QLabel("-")
        self.detail_name = QLabel("-")
        self.detail_callsign = QLabel("-")
        self.detail_type = QLabel("-")

        # Right side

        self.detail_range = QLabel("-")
        self.detail_bearing = QLabel("-")
        self.detail_rssi = QLabel("-")
        self.detail_seen = QLabel("-")

        # Lower section

        self.detail_lat = QLabel("-")
        self.detail_lon = QLabel("-")
        self.detail_sog = QLabel("-")
        self.detail_cog = QLabel("-")
        self.detail_heading = QLabel("-")
        self.detail_nav_status = QLabel("-")

        title = QLabel("Selected Vessel")
        font = title.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        title.setFont(font)

        details_layout.addWidget(title, 0, 0)

        details_layout.addWidget(QLabel("MMSI:"), 1, 0)
        details_layout.addWidget(self.detail_mmsi, 1, 1)

        details_layout.addWidget(QLabel("Range:"), 1, 2)
        details_layout.addWidget(self.detail_range, 1, 3)

        details_layout.addWidget(QLabel("Name:"), 2, 0)
        details_layout.addWidget(self.detail_name, 2, 1)

        details_layout.addWidget(QLabel("Bearing:"), 2, 2)
        details_layout.addWidget(self.detail_bearing, 2, 3)

        details_layout.addWidget(QLabel("Callsign:"), 3, 0)
        details_layout.addWidget(self.detail_callsign, 3, 1)

        details_layout.addWidget(QLabel("RSSI:"), 3, 2)
        details_layout.addWidget(self.detail_rssi, 3, 3)

        details_layout.addWidget(QLabel("Type:"), 4, 0)
        details_layout.addWidget(self.detail_type, 4, 1)

        details_layout.addWidget(QLabel("Seen:"), 4, 2)
        details_layout.addWidget(self.detail_seen, 4, 3)

        details_layout.addWidget(QLabel("Latitude:"), 5, 0)
        details_layout.addWidget(self.detail_lat, 5, 1)

        details_layout.addWidget(QLabel("Longitude:"), 5, 2)
        details_layout.addWidget(self.detail_lon, 5, 3)

        details_layout.addWidget(QLabel("SOG:"), 6, 0)
        details_layout.addWidget(self.detail_sog, 6, 1)

        details_layout.addWidget(QLabel("COG:"), 6, 2)
        details_layout.addWidget(self.detail_cog, 6, 3)

        details_layout.addWidget(QLabel("Heading:"), 7, 0)
        details_layout.addWidget(self.detail_heading, 7, 1)

        details_layout.addWidget(QLabel("Nav Status:"), 7, 2)
        details_layout.addWidget(self.detail_nav_status, 7, 3)

        target_layout.addWidget(details_widget)

        self.target_tree.setIndentation(0)
        self.target_tree.setRootIsDecorated(False)

        splitter.addWidget(self.targets_panel)

        splitter.setSizes([850, 550])

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
        # Replay progress
        #

        self.replay_progress = QProgressBar()

        self.replay_progress.setValue(0)
        self.replay_progress.setMinimumWidth(200)
        self.replay_progress.setMaximumWidth(300)

        self.faster_action.triggered.connect(self.faster_clicked)
        self.slower_action.triggered.connect(self.slower_clicked)
        toolbar.addWidget(self.replay_progress)
        self.replay_time_label = QLabel("--:--:--")
        toolbar.addWidget(self.replay_time_label)

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

    def start_clicked(self):

        self.seen_timer.start(1000)

        if self.replay.filename:
            self.current_mode = "Replay"
            self.replay_timer.start(self.current_interval_ms)

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

        for reader in self.serial_readers:
            reader.stop()

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

        self.replay_timer.stop()
        self.seen_timer.stop()
        self.stop_live_serial()

        self.current_mode = "Paused"

        self.start_action.setEnabled(True)
        self.pause_action.setEnabled(False)
        self.stop_action.setEnabled(True)

        self.update_status()

    def stop_clicked(self):

        self.replay_timer.stop()

        self.seen_timer.stop()

        self.replay.reset()

        self.stop_live_serial()

        self.current_mode = "Stopped"

        self.start_action.setEnabled(True)
        self.pause_action.setEnabled(False)
        self.stop_action.setEnabled(False)

        self.update_status()

    def clear_clicked(self):

        self.reset_session()
        self.raw_data.clear()
        self.replay.reset()

    def faster_clicked(self):

        self.replay.speed_up()

        self.speed_label.setText(f"{self.replay.speed}x")

        self.update_replay_speed()

    def slower_clicked(self):

        self.replay.slow_down()

        self.speed_label.setText(f"{self.replay.speed}x")

        self.update_replay_speed()

    def update_replay_speed(self):

        self.current_interval_ms = self.replay.interval_ms(self.replay_interval_ms)

        self.replay_timer.setInterval(self.current_interval_ms)

    def replay_next_line(self):

        if not self.replay.has_next():

            self.replay.reset()

            self.stop_clicked()

            QMessageBox.information(self, "Replay Complete", "Replay file has reached the end.")

            return

        line = self.replay.next_line()

        self.replay_progress.setValue(self.replay.progress())

        self.process_sentence(line)

        self.raw_data.verticalScrollBar().setValue(self.raw_data.verticalScrollBar().maximum())

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

        if self.selected_mmsi is not None:

            vessel = self.registry.get(self.selected_mmsi)

            if vessel:
                self.show_vessel_details(vessel)

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

        self.status_bar.showMessage(message)

    def clear_status_warning(self):

        self.status_warning = None

        self.update_status()

    def closeEvent(self, event):

        self.stop_live_serial()

        event.accept()

    def show_communications(self):

        dialog = CommunicationsDialog(self.settings)

        if dialog.exec():
            SettingsService.save(self.settings)

    def show_preferences(self):

        dialog = PreferencesDialog(self.settings)

        if dialog.exec():
            SettingsService.save(self.settings)
            apply_theme(QApplication.instance(), self.settings["theme"])
            apply_title_bar_theme(self, self.settings["theme"])
            self.map_view.set_distance_unit(self.settings["distance_unit"])

    def create_menu(self):
        menu = self.menuBar()

        file_menu = menu.addMenu("File")

        view_menu = menu.addMenu("View")

        settings_menu = menu.addMenu("Settings")

        self.show_raw_data_action = view_menu.addAction("Show Raw Data")
        self.show_raw_data_action.setCheckable(True)

        # Bidirectional sync with the toolbar toggle button — either control
        # can drive the other; setChecked() only re-emits toggled() when the
        # value actually changes, so this can't loop.
        self.show_raw_data_action.toggled.connect(self.raw_toggle.setChecked)
        self.raw_toggle.toggled.connect(self.show_raw_data_action.setChecked)

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

        self.communications_action = settings_menu.addAction("Communications")
        self.preferences_action = settings_menu.addAction("Preferences")

        self.communications_action.triggered.connect(self.show_communications)
        self.preferences_action.triggered.connect(self.show_preferences)

        self.open_replay_action = file_menu.addAction("Open Replay...")

        self.open_replay_action.triggered.connect(self.open_replay)

        help_menu = menu.addMenu("Help")

        self.help_action = help_menu.addAction("Help")
        self.about_action = help_menu.addAction("About")

        self.help_action.triggered.connect(self.show_help)
        self.about_action.triggered.connect(self.show_about)

    def show_help(self):

        dialog = HelpDialog()
        dialog.exec()

    def show_about(self):

        dialog = AboutDialog()
        dialog.exec()

    def set_column_visible(self, index, name, visible):

        self.target_tree.setColumnHidden(index, not visible)

        self.settings.setdefault("visible_columns", {})[name] = visible

        SettingsService.save(self.settings)

    def open_replay(self):

        start_dir = self.settings.get("last_replay_folder", "")

        filename, _ = QFileDialog.getOpenFileName(
            self, "Open Replay File", start_dir, "Log Files (*.txt *.log);;All Files (*)"
        )

        if not filename:
            return

        self.reset_session()

        self.replay.load_file(filename)

        from pathlib import Path

        self.settings["last_replay_folder"] = str(Path(filename).parent)

        SettingsService.save(self.settings)

        self.replay.filename = filename
        self.replay.reset()
        self.current_mode = "Replay"
        self.slower_action.setEnabled(True)
        self.faster_action.setEnabled(True)
        self.skip_to_end_action.setEnabled(True)
        self.exit_replay_action.setEnabled(True)
        self.replay_progress.setValue(0)
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

        self.replay_progress.setValue(self.replay.progress())

        self.current_mode = "Stopped"

        self.start_action.setEnabled(True)
        self.pause_action.setEnabled(False)
        self.stop_action.setEnabled(True)

        self.update_target_tree()

    def exit_replay(self):

        self.stop_clicked()

        self.replay.filename = None

        self.slower_action.setEnabled(False)
        self.faster_action.setEnabled(False)
        self.skip_to_end_action.setEnabled(False)
        self.exit_replay_action.setEnabled(False)

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

        self.detail_lat.setText("-" if vessel.lat is None else str(vessel.lat))
        self.detail_lon.setText("-" if vessel.lon is None else str(vessel.lon))
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

        self.detail_mmsi.setText("-")
        self.detail_name.setText("-")
        self.detail_callsign.setText("-")
        self.detail_type.setText("-")
        self.detail_lat.setText("-")
        self.detail_lon.setText("-")
        self.detail_sog.setText("-")
        self.detail_cog.setText("-")
        self.detail_heading.setText("-")
        self.detail_nav_status.setText("-")
        self.detail_range.setText("-")
        self.detail_bearing.setText("-")
        self.detail_rssi.setText("-")
        self.detail_seen.setText("-")

        self.update_target_tree()

    def reset_vessel_data(self, vessel):

        mmsi = vessel.mmsi
        name = vessel.name

        del self.registry.vessels[mmsi]

        fresh = self.registry.get_or_create(mmsi)

        fresh.name = name
        fresh.pinned = True

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
            print(f"Timed out vessel {mmsi}")

            del self.registry.vessels[mmsi]

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
