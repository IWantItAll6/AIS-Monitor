from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QLabel, QTableWidget, QTableWidgetItem, QDialogButtonBox,
    QHeaderView, QAbstractItemView
)
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt, QTimer


def format_rate(rate):

    return "-" if rate is None else f"{rate:.1f}/min"


class MessageStatsDialog(QDialog):
    """Receiver-wide message statistics (services/message_stats.py).
    Non-modal and refreshed every second while open, so it can be left up
    beside the map to watch the message rate — e.g. to spot a receiver
    going quiet."""

    REFRESH_MS = 1000

    def __init__(self, stats, current_time, parent=None):
        """current_time is a callable returning the time to measure the
        rate against — the replay clock during replay — or None."""

        super().__init__(parent)

        self.stats = stats
        self.current_time = current_time

        self.setWindowTitle("Message Statistics")
        self.setWindowIcon(QIcon("assets/app_icon.png"))
        self.resize(540, 560)

        layout = QVBoxLayout()
        self.setLayout(layout)

        summary = QGridLayout()

        self.total_label = QLabel("-")
        self.rate_label = QLabel("-")

        summary.addWidget(QLabel("Messages:"), 0, 0)
        summary.addWidget(self.total_label, 0, 1)
        summary.addWidget(QLabel("Rate (last minute):"), 1, 0)
        summary.addWidget(self.rate_label, 1, 1)

        stations_title = QLabel("Stations heard")
        font = stations_title.font()
        font.setBold(True)
        stations_title.setFont(font)
        summary.addWidget(stations_title, 2, 0, 1, 2)

        self.class_labels = {}

        for row, (station_class, _) in enumerate(stats.station_class_counts(), start=3):

            value = QLabel("0")
            summary.addWidget(QLabel(f"{station_class}:"), row, 0)
            summary.addWidget(value, row, 1)

            self.class_labels[station_class] = value

        summary.setColumnStretch(1, 1)

        layout.addLayout(summary)

        self.type_table = QTableWidget(0, 4)
        self.type_table.setHorizontalHeaderLabels(["Type", "Description", "Count", "%"])
        self.type_table.verticalHeader().setVisible(False)
        self.type_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.type_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.type_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.type_table.setWordWrap(False)

        header = self.type_table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (0, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self.type_table)

        note = QLabel("Counts cover the session since it was last cleared (or since the replay was scrubbed).")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)

        self.refresh()

    def showEvent(self, event):

        super().showEvent(event)
        self.refresh()
        self.refresh_timer.start(self.REFRESH_MS)

    def hideEvent(self, event):

        super().hideEvent(event)
        self.refresh_timer.stop()

    def refresh(self):

        self.total_label.setText(f"{self.stats.total:,}")
        self.rate_label.setText(format_rate(self.stats.rate_per_minute(self.current_time())))

        for station_class, count in self.stats.station_class_counts():
            self.class_labels[station_class].setText(str(count))

        rows = self.stats.type_breakdown()

        self.type_table.setRowCount(len(rows))

        for row, (msg_type, name, count, percent) in enumerate(rows):

            cells = (str(msg_type), name, f"{count:,}", f"{percent:.1f}")

            for column, text in enumerate(cells):

                item = QTableWidgetItem(text)

                if column != 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

                self.type_table.setItem(row, column, item)
