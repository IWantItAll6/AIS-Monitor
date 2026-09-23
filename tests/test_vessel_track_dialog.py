from datetime import datetime

from services.file_analysis_service import VesselAnalysis
from ui.vessel_track_dialog import VesselTrackDialog


def make_analysis():

    analysis = VesselAnalysis(mmsi=111111111, name="ALPHA")

    analysis.track = [
        (datetime(2026, 1, 1, 0, 0, 0), 50.0, -2.0),
        (datetime(2026, 1, 1, 0, 0, 10), 50.5, -2.5),
        (datetime(2026, 1, 1, 0, 0, 20), 51.0, -3.0),
    ]

    return analysis


def test_title_shows_vessel_name_and_mmsi(qapp):

    dialog = VesselTrackDialog(make_analysis())

    assert "ALPHA" in dialog.windowTitle()
    assert "111111111" in dialog.windowTitle()


def test_showing_the_dialog_fits_the_map_to_the_full_track(qapp):

    analysis = make_analysis()
    dialog = VesselTrackDialog(analysis)

    dialog.show()

    assert dialog.map_view.static_track == analysis.track
    # Midpoint of the track's lat span (50.0..51.0).
    assert dialog.map_view.center_lat == 50.5

    dialog.close()


def test_export_png_saves_a_grab_of_the_map_when_a_path_is_chosen(qapp, monkeypatch, tmp_path):

    dialog = VesselTrackDialog(make_analysis())
    dialog.show()

    out_path = str(tmp_path / "track.png")

    monkeypatch.setattr(
        "ui.vessel_track_dialog.QFileDialog.getSaveFileName", lambda *a, **kw: (out_path, "PNG Image (*.png)")
    )

    dialog.export_png()

    assert (tmp_path / "track.png").exists()

    dialog.close()


def test_export_png_does_nothing_when_the_save_dialog_is_cancelled(qapp, monkeypatch, tmp_path):

    dialog = VesselTrackDialog(make_analysis())
    dialog.show()

    monkeypatch.setattr("ui.vessel_track_dialog.QFileDialog.getSaveFileName", lambda *a, **kw: ("", ""))

    dialog.export_png()

    assert list(tmp_path.iterdir()) == []

    dialog.close()
