import csv
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTreeWidget,
    QPushButton,
    QLabel,
    QDialogButtonBox,
    QFileDialog
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QFontMetrics

from ui.vessel_tree_item import VesselTreeItem
from services.geo import convert_distance, UNIT_SUFFIX
from services.file_analysis_service import format_duration


def _distance_cell(field_name):
    """A column value_fn for a nm-valued VesselAnalysis field — converts to
    the dialog's chosen distance_unit at display time, keeping the
    underlying data always in nm."""

    def value_fn(analysis, distance_unit):

        value_nm = getattr(analysis, field_name)

        if value_nm is None:
            return "-", None

        converted = convert_distance(value_nm, distance_unit)

        return f"{converted:.2f}", converted

    return value_fn


# Each column is (label, value_fn(analysis, distance_unit) -> (display_text,
# sort_value)) — one shared definition drives headers, row cells, and CSV
# export, so there's no separate index bookkeeping (e.g. "distance columns
# are indices 7-9") to keep in sync when columns are added or reordered.
# "{unit}" in a label is filled in once the distance unit is known.
#
# Ordered for density and relevance, not just grouping — identity first,
# then the reception-quality stats that are the actual point of this
# feature, with First/Last Seen last since a full "YYYY-MM-DD HH:MM:SS"
# timestamp eats much more column width than anything else here for
# comparatively lower everyday relevance than Duration (kept earlier, next
# to the other at-a-glance stats). Callsign dropped entirely — judged not
# worth its column space.
BASE_COLUMNS = [
    ("MMSI", lambda a, u: (str(a.mmsi), a.mmsi)),
    ("Name", lambda a, u: (a.name or "-", None)),
    # Every message from this target, any type — position reports AND
    # static/voyage data (name/callsign/ship type, sent on its own separate
    # ~6min cadence). Deliberately NOT the same count as "Position TX"
    # below: that column is scoped to only the position reports Expected/
    # Loss% can compare against, so the two will routinely differ by
    # however many static-data messages were also received.
    ("Total TX", lambda a, u: (str(a.tx_count), a.tx_count)),
]

# Right after Total TX since Expected/Position TX are a closer look at that
# same "how many transmissions" question, not a separate topic like
# RSSI/speed/range below. Unlike every other column here, these three are
# an estimate, not a direct count — see the disclaimer label built in
# __init__.
TX_LOSS_COLUMNS = [
    ("Expected", lambda a, u: (f"{a.expected_tx:.1f}" if a.expected_tx else "-", a.expected_tx)),
    ("Position TX", lambda a, u: (str(a.position_report_count), a.position_report_count)),
    (
        "Loss %",
        lambda a, u: (
            (f"{a.estimated_tx_loss_percent:.1f}", a.estimated_tx_loss_percent)
            if a.estimated_tx_loss_percent is not None else ("-", None)
        )
    ),
]

REST_COLUMNS = [
    ("Min RSSI", lambda a, u: (str(a.rssi_min) if a.rssi_min is not None else "-", a.rssi_min)),
    ("Max RSSI", lambda a, u: (str(a.rssi_max) if a.rssi_max is not None else "-", a.rssi_max)),
    ("Avg RSSI", lambda a, u: (f"{a.avg_rssi:.1f}" if a.avg_rssi is not None else "-", a.avg_rssi)),
    ("Speed (kn)", lambda a, u: (f"{a.avg_speed:.1f}" if a.avg_speed is not None else "-", a.avg_speed)),
    ("Distance ({unit})", _distance_cell("distance_traveled_nm")),
    ("Closest ({unit})", _distance_cell("range_min_nm")),
    ("Furthest ({unit})", _distance_cell("range_max_nm")),
    ("Duration", lambda a, u: (format_duration(a.duration_seconds), a.duration_seconds)),
    (
        "First Seen",
        lambda a, u: (a.first_seen.strftime("%Y-%m-%d %H:%M:%S") if a.first_seen else "-", a.first_seen)
    ),
    (
        "Last Seen",
        lambda a, u: (a.last_seen.strftime("%Y-%m-%d %H:%M:%S") if a.last_seen else "-", a.last_seen)
    ),
]


class FileAnalysisDialog(QDialog):
    """Read-only results viewer for services.file_analysis_service.analyze_file()
    — a plain sortable list (VesselTreeItem is reused from the main target
    tree purely for its numeric-aware sort compare; no pinning concept
    applies here) plus a CSV export, following the same
    QFileDialog.getSaveFileName pattern as MainWindow.export_targets_csv."""

    # Breathing room added on top of the widest header/cell text in
    # fit_columns_to_contents() — enough for the column to not feel
    # cramped against its neighbor, without reintroducing the bloat that
    # method replaces resizeColumnToContents() to get rid of.
    COLUMN_PADDING = 16

    def __init__(self, filename, analyses, distance_unit="NM"):

        super().__init__()

        self.filename = filename
        self.analyses = analyses
        self.distance_unit = distance_unit

        self.columns = BASE_COLUMNS + TX_LOSS_COLUMNS + REST_COLUMNS

        self.setWindowTitle("File Analysis")
        self.setWindowIcon(QIcon("assets/app_icon.png"))
        self.resize(1150, 550)

        layout = QVBoxLayout()
        self.setLayout(layout)

        target_word = "target" if len(analyses) == 1 else "targets"
        header_label = QLabel(f"{Path(filename).name} — {len(analyses)} {target_word}")
        layout.addWidget(header_label)

        # Permanent, not a one-time dialog — Expected/Position TX/Loss % are
        # the only estimated (not directly counted) columns here, so this
        # stays visible every time rather than only being shown once up
        # front.
        disclaimer = QLabel(
            "Position TX (unlike Total TX) counts only position reports, not static/voyage data — "
            "Expected and Loss % (Class A & B) are an estimate based on each vessel's reported speed "
            "and the ITU-R M.1371 reporting-interval standard, not an exact count. Loss % can be "
            "negative when a vessel reports faster than its speed implied at the start of a gap."
        )
        disclaimer.setWordWrap(True)
        font = disclaimer.font()
        font.setPointSize(max(font.pointSize() - 1, 7))
        font.setItalic(True)
        disclaimer.setFont(font)
        layout.addWidget(disclaimer)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(self.column_labels())
        self.tree.setRootIsDecorated(False)
        self.tree.setSortingEnabled(True)
        self.tree.setAlternatingRowColors(True)

        header = self.tree.header()
        header.setStretchLastSection(False)

        layout.addWidget(self.tree)

        self.populate()
        self.fit_columns_to_contents()

        button_layout = QHBoxLayout()

        self.export_button = QPushButton("Export CSV...")
        self.export_button.clicked.connect(self.export_csv)
        button_layout.addWidget(self.export_button)

        button_layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        button_layout.addWidget(buttons)

        layout.addLayout(button_layout)

    def column_labels(self):

        unit_suffix = UNIT_SUFFIX.get(self.distance_unit, self.distance_unit)

        return [label.format(unit=unit_suffix) for label, _ in self.columns]

    def row_cells(self, analysis):
        """Returns one (display_text, sort_value) pair per column —
        sort_value is None for plain-text columns (Name), which fall back
        to VesselTreeItem's default string comparison."""

        return [value_fn(analysis, self.distance_unit) for _, value_fn in self.columns]

    def populate(self):

        for analysis in self.analyses:

            cells = self.row_cells(analysis)

            item = VesselTreeItem([text for text, _ in cells])

            for column, (_, sort_value) in enumerate(cells):

                if sort_value is not None:
                    item.setData(column, Qt.ItemDataRole.UserRole, sort_value)

            self.tree.addTopLevelItem(item)

    def fit_columns_to_contents(self):
        """Sizes every column to its own widest header/cell text, measured
        directly via QFontMetrics rather than QTreeWidget's built-in
        resizeColumnToContents() — that one reserves a fixed chunk of extra
        width per column (icon/decoration space QTreeWidgetItem budgets for
        even with no icon ever set), which barely shows on a wide column
        but is a large fraction of a narrow one's own width (e.g. "Loss %"
        or "Min RSSI"), making short columns look padded far beyond their
        actual text."""

        header_metrics = QFontMetrics(self.tree.header().font())
        item_metrics = QFontMetrics(self.tree.font())

        for column, label in enumerate(self.column_labels()):

            widest = header_metrics.horizontalAdvance(label)

            for row in range(self.tree.topLevelItemCount()):
                text = self.tree.topLevelItem(row).text(column)
                widest = max(widest, item_metrics.horizontalAdvance(text))

            self.tree.setColumnWidth(column, widest + self.COLUMN_PADDING)

    def export_csv(self):

        default_name = f"{Path(self.filename).stem}_analysis.csv"

        filename, _ = QFileDialog.getSaveFileName(self, "Export Analysis as CSV", default_name, "CSV File (*.csv)")

        if not filename:
            return

        with open(filename, "w", newline="", encoding="utf-8") as f:

            writer = csv.writer(f)

            writer.writerow(self.column_labels())

            for analysis in self.analyses:
                writer.writerow([text for text, _ in self.row_cells(analysis)])
