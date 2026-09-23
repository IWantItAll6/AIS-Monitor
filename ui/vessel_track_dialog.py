from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QDialogButtonBox, QFileDialog

from ui.map_panel import MapPanel


class VesselTrackDialog(QDialog):
    """Shows one File Analysis vessel's complete, untrimmed journey — the
    live map can't do this itself, since a live Vessel's track is bounded
    by the Track Length setting, but a VesselAnalysis (services.
    file_analysis_service) keeps the whole file's track. Owns its own
    MapPanel rather than reusing MainWindow's, since FileAnalysisDialog (the
    caller) has no reference to it and is itself modal."""

    def __init__(self, analysis, parent=None):

        super().__init__(parent)

        self.analysis = analysis

        self.setWindowTitle(f"Track — {analysis.name or 'Unnamed'} ({analysis.mmsi})")
        self.resize(700, 600)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.map_view = MapPanel(
            "data/naturalearth/ne_10m_land/ne_10m_land.shp",
            "data/naturalearth/ne_10m_populated_places/ne_10m_populated_places_simple.shp",
            "data/geonames/gb_towns.json"
        )
        layout.addWidget(self.map_view)

        button_layout = QHBoxLayout()

        self.export_button = QPushButton("Export PNG...")
        self.export_button.clicked.connect(self.export_png)
        button_layout.addWidget(self.export_button)

        button_layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        button_layout.addWidget(buttons)

        layout.addLayout(button_layout)

    def showEvent(self, event):

        super().showEvent(event)

        # Deferred to here rather than __init__ — fit_to_points() needs the
        # map's real, laid-out size, which isn't final until the dialog is
        # actually shown.
        self.map_view.set_static_track(self.analysis.track)

    def export_png(self):

        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Track PNG", "track.png", "PNG Image (*.png)"
        )

        if not filename:
            return

        self.map_view.grab().save(filename, "PNG")
