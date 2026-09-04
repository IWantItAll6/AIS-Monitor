from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QDialogButtonBox, QPushButton, QLabel
from PySide6.QtGui import QIcon


class ErrorLogDialog(QDialog):
    """In-app viewer for the current session's services/error_log.py
    entries — the discoverable counterpart to the on-disk log, for a
    packaged build that has no console to show parser errors in otherwise."""

    def __init__(self, error_log):

        super().__init__()

        self.error_log = error_log

        self.setWindowTitle("Session Error Log")
        self.setWindowIcon(QIcon("assets/app_icon.png"))
        self.resize(700, 400)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text)

        path_label = QLabel(f"Full history is also written to: {self.error_log.path}")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)

        button_layout = QHBoxLayout()

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        button_layout.addWidget(refresh_button)

        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.clear)
        button_layout.addWidget(clear_button)

        button_layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        button_layout.addWidget(buttons)

        layout.addLayout(button_layout)

        self.refresh()

    def refresh(self):

        if not self.error_log.entries:
            self.text.setPlainText("No errors this session.")
            return

        lines = []

        for entry in self.error_log.entries:

            line = f"[{entry['time'].strftime('%H:%M:%S')}] {entry['source']}: {entry['message']}"

            if entry["sentence"]:
                line += f"\n    {entry['sentence']}"

            lines.append(line)

        self.text.setPlainText("\n".join(lines))

    def clear(self):

        self.error_log.clear()
        self.refresh()
