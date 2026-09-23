from datetime import datetime

import ui.file_analysis_dialog as file_analysis_dialog_module
from services.file_analysis_service import VesselAnalysis
from ui.file_analysis_dialog import FileAnalysisDialog


def make_dialog(analyses):

    return FileAnalysisDialog("irrelevant.log", analyses)


def test_show_track_button_disabled_with_no_selection(qapp):

    with_track = VesselAnalysis(mmsi=111111111, name="ALPHA")
    with_track.track = [(datetime(2026, 1, 1), 50.0, -2.0)]

    dialog = make_dialog([with_track])

    assert not dialog.show_track_button.isEnabled()


def test_show_track_button_enabled_only_for_a_vessel_with_track_data(qapp):

    with_track = VesselAnalysis(mmsi=111111111, name="ALPHA")
    with_track.track = [(datetime(2026, 1, 1), 50.0, -2.0)]

    no_track = VesselAnalysis(mmsi=222222222, name="BRAVO")

    dialog = make_dialog([with_track, no_track])

    row_with_track = next(
        r for r in range(dialog.tree.topLevelItemCount())
        if dialog.tree.topLevelItem(r).text(0) == "111111111"
    )
    row_no_track = next(
        r for r in range(dialog.tree.topLevelItemCount())
        if dialog.tree.topLevelItem(r).text(0) == "222222222"
    )

    dialog.tree.setCurrentItem(dialog.tree.topLevelItem(row_with_track))
    assert dialog.show_track_button.isEnabled()

    dialog.tree.setCurrentItem(dialog.tree.topLevelItem(row_no_track))
    assert not dialog.show_track_button.isEnabled()


def test_show_track_opens_a_dialog_for_the_selected_vessel(qapp, monkeypatch):

    with_track = VesselAnalysis(mmsi=111111111, name="ALPHA")
    with_track.track = [(datetime(2026, 1, 1), 50.0, -2.0)]

    dialog = make_dialog([with_track])
    dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))

    opened = []

    class FakeTrackDialog:

        def __init__(self, analysis, parent=None):
            opened.append(analysis)

        def exec(self):
            pass

    monkeypatch.setattr(file_analysis_dialog_module, "VesselTrackDialog", FakeTrackDialog)

    dialog.show_track()

    assert opened == [with_track]
