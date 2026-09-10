import csv
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTreeWidget,
    QHeaderView,
    QPushButton,
    QLabel,
    QDialogButtonBox,
    QFileDialog
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from ui.vessel_tree_item import VesselTreeItem
from services.geo import convert_distance, UNIT_SUFFIX
from services.file_analysis_service import format_duration

# Ordered for density and relevance, not just grouping — identity first,
# then the reception-quality stats that are the actual point of this
# feature, with First/Last Seen last since a full "YYYY-MM-DD HH:MM:SS"
# timestamp eats much more column width than anything else here for
# comparatively lower everyday relevance than Duration (which is kept
# earlier, next to the other at-a-glance stats). Callsign dropped entirely
# — judged not worth its column space.
COLUMN_LABELS = [
    "MMSI", "Name", "TX", "Min RSSI", "Max RSSI", "Avg RSSI", "Speed (kn)",
    "Distance", "Closest", "Furthest", "Duration", "First Seen", "Last Seen"
]

# Indices into COLUMN_LABELS whose header needs the distance unit appended
# (e.g. "Distance (NM)") — kept separate from the fixed labels above so the
# unit-dependent ones can be built once the unit is known.
DISTANCE_COLUMNS = {7: "Distance", 8: "Closest", 9: "Furthest"}


class FileAnalysisDialog(QDialog):
    """Read-only results viewer for services.file_analysis_service.analyze_file()
    — a plain sortable list (VesselTreeItem is reused from the main target
    tree purely for its numeric-aware sort compare; no pinning concept
    applies here) plus a CSV export, following the same
    QFileDialog.getSaveFileName pattern as MainWindow.export_targets_csv."""

    def __init__(self, filename, analyses, distance_unit="NM"):

        super().__init__()

        self.filename = filename
        self.analyses = analyses
        self.distance_unit = distance_unit

        self.setWindowTitle("File Analysis")
        self.setWindowIcon(QIcon("assets/app_icon.png"))
        self.resize(1150, 550)

        layout = QVBoxLayout()
        self.setLayout(layout)

        target_word = "target" if len(analyses) == 1 else "targets"
        header_label = QLabel(f"{Path(filename).name} — {len(analyses)} {target_word}")
        layout.addWidget(header_label)

        self.tree = QTreeWidget()

        unit_suffix = UNIT_SUFFIX.get(distance_unit, distance_unit)
        labels = list(COLUMN_LABELS)

        for index, base_label in DISTANCE_COLUMNS.items():
            labels[index] = f"{base_label} ({unit_suffix})"

        self.tree.setHeaderLabels(labels)
        self.tree.setRootIsDecorated(False)
        self.tree.setSortingEnabled(True)
        self.tree.setAlternatingRowColors(True)

        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self.tree)

        self.populate()

        button_layout = QHBoxLayout()

        self.export_button = QPushButton("Export CSV...")
        self.export_button.clicked.connect(self.export_csv)
        button_layout.addWidget(self.export_button)

        button_layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        button_layout.addWidget(buttons)

        layout.addLayout(button_layout)

    def row_cells(self, analysis):
        """Returns one (display_text, sort_value) pair per column —
        sort_value is None for plain-text columns (Name), which fall back
        to VesselTreeItem's default string comparison."""

        def distance_cell(value_nm):

            if value_nm is None:
                return "-", None

            converted = convert_distance(value_nm, self.distance_unit)

            return f"{converted:.2f}", converted

        return [
            (str(analysis.mmsi), analysis.mmsi),
            (analysis.name or "-", None),
            (str(analysis.tx_count), analysis.tx_count),
            (str(analysis.rssi_min) if analysis.rssi_min is not None else "-", analysis.rssi_min),
            (str(analysis.rssi_max) if analysis.rssi_max is not None else "-", analysis.rssi_max),
            (f"{analysis.avg_rssi:.1f}" if analysis.avg_rssi is not None else "-", analysis.avg_rssi),
            (f"{analysis.avg_speed:.1f}" if analysis.avg_speed is not None else "-", analysis.avg_speed),
            distance_cell(analysis.distance_traveled_nm),
            distance_cell(analysis.range_min_nm),
            distance_cell(analysis.range_max_nm),
            (format_duration(analysis.duration_seconds), analysis.duration_seconds),
            (
                analysis.first_seen.strftime("%Y-%m-%d %H:%M:%S") if analysis.first_seen else "-",
                analysis.first_seen
            ),
            (
                analysis.last_seen.strftime("%Y-%m-%d %H:%M:%S") if analysis.last_seen else "-",
                analysis.last_seen
            ),
        ]

    def populate(self):

        for analysis in self.analyses:

            cells = self.row_cells(analysis)

            item = VesselTreeItem([text for text, _ in cells])

            for column, (_, sort_value) in enumerate(cells):

                if sort_value is not None:
                    item.setData(column, Qt.ItemDataRole.UserRole, sort_value)

            self.tree.addTopLevelItem(item)

        for column in range(self.tree.columnCount()):
            self.tree.resizeColumnToContents(column)

    def export_csv(self):

        default_name = f"{Path(self.filename).stem}_analysis.csv"

        filename, _ = QFileDialog.getSaveFileName(self, "Export Analysis as CSV", default_name, "CSV File (*.csv)")

        if not filename:
            return

        with open(filename, "w", newline="", encoding="utf-8") as f:

            writer = csv.writer(f)

            unit_suffix = UNIT_SUFFIX.get(self.distance_unit, self.distance_unit)
            labels = list(COLUMN_LABELS)

            for index, base_label in DISTANCE_COLUMNS.items():
                labels[index] = f"{base_label} ({unit_suffix})"

            writer.writerow(labels)

            for analysis in self.analyses:
                writer.writerow([text for text, _ in self.row_cells(analysis)])
