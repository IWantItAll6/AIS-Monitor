from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPolygonF, QPen, QTextDocument
from PySide6.QtCore import Qt, QPointF, QRectF, QUrl

from ui.map_panel import MapPanel

# Each entry pairs a marker "kind" (drawn by _draw_legend_icon, mirroring
# MapPanel.draw_vessels' shapes) with the label shown next to it in the
# Help dialog's marker legend image.
LEGEND_ENTRIES = [
    ("own_ship", "Own position (GNSS fix)"),
    ("vessel_heading", "Vessel — heading/COG known"),
    ("vessel_no_heading", "Vessel — heading/COG unknown"),
    ("pinned", "Pinned vessel"),
    ("base_station", "Base station"),
    ("aton", "Aid to Navigation"),
    ("aton_virtual", "Aid to Navigation — virtual"),
    ("safety", "SART / MOB / EPIRB beacon"),
]

_LEGEND_COLUMNS = 2
_LEGEND_CELL_WIDTH = 220
_LEGEND_CELL_HEIGHT = 32
_LEGEND_ICON_X = 16
_LEGEND_TEXT_COLOR = QColor(225, 225, 225)


def _draw_legend_icon(painter, kind, center):
    """Mirrors MapPanel.draw_vessels' per-category shapes and colors, minus
    the heading rotation and label-placement logic that only make sense for
    a live, moving marker rather than a static legend entry."""

    vessel_color = QColor(MapPanel.DEFAULT_VESSEL_COLOR)
    pinned_color = QColor(MapPanel.DEFAULT_PINNED_COLOR)

    if kind in ("own_ship", "vessel_heading", "pinned"):

        color = {
            "own_ship": MapPanel.OWN_SHIP_COLOR,
            "vessel_heading": vessel_color,
            "pinned": pinned_color,
        }[kind]

        if kind == "pinned":
            painter.setPen(QPen(MapPanel.PIN_RING_COLOR, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, MapPanel.PIN_RING_RADIUS, MapPanel.PIN_RING_RADIUS)

        painter.setPen(QPen(color, 1))
        painter.setBrush(color)
        painter.save()
        painter.translate(center)
        painter.drawPolygon(MapPanel.VESSEL_TRIANGLE)
        painter.restore()

    elif kind == "vessel_no_heading":
        painter.setPen(QPen(vessel_color, 1))
        painter.setBrush(vessel_color)
        painter.drawEllipse(center, 4, 4)

    elif kind == "base_station":
        painter.setPen(QPen(vessel_color, 1))
        painter.setBrush(vessel_color)
        half = MapPanel.BASE_STATION_HALF_SIZE
        painter.drawRect(QRectF(center.x() - half, center.y() - half, half * 2, half * 2))

    elif kind in ("aton", "aton_virtual"):
        half = MapPanel.ATON_HALF_SIZE
        diamond = QPolygonF([
            center + QPointF(0, -half), center + QPointF(half, 0),
            center + QPointF(0, half), center + QPointF(-half, 0),
        ])

        if kind == "aton_virtual":
            painter.setPen(QPen(vessel_color, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        else:
            painter.setPen(QPen(vessel_color, 1))
            painter.setBrush(vessel_color)

        painter.drawPolygon(diamond)

    elif kind == "safety":
        painter.setPen(QPen(MapPanel.SAFETY_MARK_COLOR, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        r = MapPanel.SAFETY_MARK_RADIUS
        painter.drawEllipse(center, r, r)
        painter.drawLine(center + QPointF(-r, 0), center + QPointF(r, 0))
        painter.drawLine(center + QPointF(0, -r), center + QPointF(0, r))


def build_marker_legend_pixmap():
    """A reference image for the Help dialog showing every map marker shape
    side by side with a label. Generated from MapPanel's own shape/color
    constants rather than a separate hand-drawn asset, so it can't silently
    drift out of sync with what the map actually draws.
    """

    rows = -(-len(LEGEND_ENTRIES) // _LEGEND_COLUMNS)  # ceil division

    width = _LEGEND_CELL_WIDTH * _LEGEND_COLUMNS
    height = _LEGEND_CELL_HEIGHT * rows

    pixmap = QPixmap(width, height)

    # Markers are only ever actually seen against the map's water color —
    # not the app's light/dark UI theme — so the legend reproduces that
    # background rather than adapting to the current theme. In particular,
    # the white pin ring would be invisible against a light background.
    pixmap.fill(MapPanel.WATER_COLOR)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    font = painter.font()
    font.setPointSize(9)
    painter.setFont(font)

    metrics = painter.fontMetrics()

    for i, (kind, label) in enumerate(LEGEND_ENTRIES):

        col = i % _LEGEND_COLUMNS
        row = i // _LEGEND_COLUMNS

        cell_x = col * _LEGEND_CELL_WIDTH
        cell_y = row * _LEGEND_CELL_HEIGHT

        center = QPointF(cell_x + _LEGEND_ICON_X, cell_y + _LEGEND_CELL_HEIGHT / 2)

        _draw_legend_icon(painter, kind, center)

        painter.setPen(_LEGEND_TEXT_COLOR)
        painter.drawText(
            QPointF(cell_x + _LEGEND_ICON_X + 20, center.y() + metrics.ascent() / 2 - 1),
            label
        )

    painter.end()

    return pixmap

HELP_HTML = """
<h2>AIS Monitor — Help</h2>

<h3>Modes</h3>
<p>
<b>Live</b> mode reads from a serial AIS receiver (and optionally a separate
GNSS receiver) configured under <b>Settings &gt; Communications</b>. Every
live session is automatically recorded to disk in the same format Replay
reads (see <b>Recording</b> below), so it can be played back later.
<b>Replay</b> mode plays back a previously captured log file instead —
use <b>File &gt; Open Replay...</b> to load one, or <b>File &gt; Load
Sample Data</b> to try the app immediately with a bundled example, no
receiver required. Once a replay file is loaded, <b>Start</b> plays it
back; <b>Slower</b>/<b>Faster</b> change the playback speed, and <b>Exit
Replay</b> returns to live mode.
</p>
<p>
At <b>1x</b>, replay matches the file's own recorded timing — a 10-second
gap between two messages plays back over roughly 10 real seconds, and
several sentences logged at the exact same instant (common with real
receiver output) always play together rather than being spread out.
<b>Slower</b>/<b>Faster</b> scale that real-time pacing up or down.
</p>
<p>
Drag the scrubber in the toolbar to jump to a different point in a loaded
replay. A large <b>Catching up…</b> badge appears on the map briefly while
it replays the skipped span in the background, so tracks and vessel state
arrive at the same point they'd be at if you'd played through normally —
uncheck <b>Animate on drop</b> next to the scrubber to jump straight there
instead.
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
vessel without changing the current zoom level. Type in the search box
above the list to filter it by MMSI or name.
</p>
<p>
Click the star column to <b>pin</b> a vessel — pinned vessels always sort to
the top of the list regardless of which column you're sorting by, are
immune to the normal timeout that otherwise removes vessels that haven't
been heard from recently, and show up gold instead of orange on the map.
</p>
<p>
Use <b>View &gt; Select Columns</b> to show or hide individual columns in
the list, and <b>View &gt; Vessel Detail Fields</b> to do the same for the
detail panel below it (including fields not shown by default, like
destination, draught, IMO number, rate of turn, length, and beam) — both
sets of choices are remembered between sessions. <b>RSSI</b> (received
signal strength) only populates for compatible receiver hardware that
reports it.
</p>
<p>
<b>File &gt; Export</b> saves a screenshot of the whole window, or the
current target list, to a file.
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
<p>
Other AIS station types use their own marker shape rather than the vessel
triangle: a <b>square</b> is a base station, a <b>diamond</b> is an Aid to
Navigation (hollow for a virtual AtoN with no physical structure), and a
<b>circle with a cross</b> is a SART, MOB, or EPIRB distress beacon — pinning
one of these shifts it from bright red to a softer pastel red rather than
gold, so it never stops reading as a distress mark.
</p>
<p><img src="legend://markers"></p>
<p>
<b>View &gt; Show Place Names</b> toggles town/city labels on the map. In
<b>Preferences &gt; Map</b> you can further restrict labels to only towns
within a given distance of the coast. The <b>Zoom to Fit</b> command
(Run menu, or Ctrl+0) reframes the map to show every currently positioned
target.
</p>

<h3>Raw Data</h3>
<p>
The <b>Raw Data</b> panel shows incoming sentences as they arrive. Use the
<b>Show:</b> checkboxes to filter what's displayed by sentence type (AIS,
GNSS, RSSI, or anything else) — this only affects what's shown, not what's
processed.
</p>

<h3>Recording</h3>
<p>
Live sessions are recorded automatically to the <b>Recordings Folder</b>
set in <b>Preferences</b> — nothing is ever deleted automatically, so if
that folder grows large, a one-time warning appears (its size threshold,
or turning the warning off entirely, is also set there).
</p>

<h3>Settings</h3>
<p>
<b>Communications</b> configures the AIS (and optional separate GNSS)
serial port and baud rate. Use each port's <b>Test</b> button to listen on
it briefly and confirm data is actually arriving, before starting a full
session. If your receiver doesn't communicate correctly, check the
collapsed <b>Advanced</b> section:
</p>
<p>
The <b>Serial Format</b> describes how each byte of data is framed on the
wire — it's written as three parts, e.g. <b>8N1</b>:
</p>
<ul>
<li><b>Data bits</b> (the first number, e.g. 8 or 7) — how many bits carry
the actual data in each byte.</li>
<li><b>Parity</b> (the letter) — a basic error-check bit: <b>N</b>one,
<b>E</b>ven, or <b>O</b>dd.</li>
<li><b>Stop bits</b> (the last number) — how many bits mark the end of a
byte.</li>
</ul>
<p>
<b>8N1</b> is the standard default for NMEA 0183 equipment (which is what
AIS and GNSS receivers speak) and covers most receivers. If yours needs
something else, it'll be in the receiver's manual — AIS and GNSS can be
configured independently here, since combined and split receiver setups
sometimes use different formats.
</p>
<p>
<b>Preferences</b> sets the app's light/dark theme, the vessel and pinned
marker colors, distance units (nautical miles, miles, or km — used
throughout the target list, detail panel, and map scale bar), how long a
vessel can go unheard-from before it's removed from the list, how much
track history is kept per vessel, and the recording settings above.
</p>

<h3>Keyboard Shortcuts</h3>
<ul>
<li><b>F5</b> — Start</li>
<li><b>F6</b> — Pause</li>
<li><b>F7</b> — Stop</li>
<li><b>Ctrl+Shift+C</b> — Clear</li>
<li><b>Ctrl+G</b> — Center map on GNSS fix</li>
<li><b>Ctrl+End</b> — Skip to end of replay</li>
<li><b>Ctrl+=</b> / <b>Ctrl+-</b> — Zoom map in/out</li>
<li><b>Ctrl+0</b> — Zoom to fit all targets</li>
<li><b>Ctrl+O</b> — Open Replay...</li>
</ul>
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

        # Registered before setHtml() so the <img src="legend://markers">
        # reference in HELP_HTML already resolves when the document parses.
        text.document().addResource(
            QTextDocument.ResourceType.ImageResource,
            QUrl("legend://markers"),
            build_marker_legend_pixmap()
        )

        text.setHtml(HELP_HTML)

        layout.addWidget(text)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)

        layout.addWidget(buttons)
