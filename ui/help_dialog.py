from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox
from PyQt6.QtGui import QIcon

HELP_HTML = """
<h2>AIS Monitor — Help</h2>

<h3>Modes</h3>
<p>
<b>Live</b> mode reads from a serial AIS receiver (and optionally a separate
GNSS receiver) configured under <b>Settings &gt; Communications</b>.
<b>Replay</b> mode plays back a previously captured log file instead —
use <b>File &gt; Open Replay...</b> to load one. Once a replay file is
loaded, <b>Start</b> plays it back; <b>Slower</b>/<b>Faster</b> change the
playback speed, and <b>Exit Replay</b> returns to live mode.
</p>
<p>
<b>Pause</b> halts processing without losing the current session. <b>Stop</b>
halts and rewinds a loaded replay back to the start. <b>Clear</b> wipes the
current session's targets and raw data — pinned (starred) vessels survive a
clear, but have their tracked data reset back to just identity (MMSI/name),
ready to pick up fresh readings.
</p>

<h3>The Target List</h3>
<p>
Each row is a tracked vessel. Click a row to select it and see its full
details below the list. Double-click a row to center the map on that
vessel without changing the current zoom level.
</p>
<p>
Click the star column to <b>pin</b> a vessel — pinned vessels always sort to
the top of the list regardless of which column you're sorting by, are
immune to the normal timeout that otherwise removes vessels that haven't
been heard from recently, and show up gold instead of orange on the map.
</p>
<p>
Use <b>View &gt; Select Columns</b> to show or hide individual columns —
your choices are remembered between sessions.
</p>

<h3>The Map</h3>
<p>
Drag to pan, scroll to zoom. The scale bar in the bottom-left shows the
current scale in nautical miles. Click a vessel's marker to select it (same
as clicking its row in the list); double-click a marker to pin/unpin it.
The <b>⊙ GNSS</b> toolbar button centers the map on your own position, if
there's a GNSS fix.
</p>
<p>
Vessels are drawn as a triangle pointing in their heading (or course over
ground, if heading isn't reported) when known, or a plain dot otherwise.
A trailing line shows each vessel's recent track — how far back it goes is
set by <b>Preferences &gt; Track Length</b>.
</p>

<h3>Raw Data</h3>
<p>
The <b>Raw Data</b> panel shows incoming sentences as they arrive. Use the
<b>Show:</b> checkboxes to filter what's displayed by sentence type (AIS,
GNSS, RSSI, or anything else) — this only affects what's shown, not what's
processed.
</p>

<h3>Settings</h3>
<p>
<b>Communications</b> configures the AIS (and optional separate GNSS)
serial port, baud rate, and — under the collapsed <b>Advanced</b> section —
the data/parity/stop-bit format (8N1 covers most equipment).
</p>
<p>
<b>Preferences</b> sets the app's light/dark theme, how long a vessel can
go unheard-from before it's removed from the list, and how much track
history is kept per vessel.
</p>
"""


class HelpDialog(QDialog):

    def __init__(self):

        super().__init__()

        self.setWindowTitle("AIS Monitor Help")
        self.setWindowIcon(QIcon("assets/app_icon.png"))
        self.resize(640, 640)

        layout = QVBoxLayout()
        self.setLayout(layout)

        text = QTextEdit()
        text.setReadOnly(True)
        text.setHtml(HELP_HTML)

        layout.addWidget(text)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)

        layout.addWidget(buttons)
