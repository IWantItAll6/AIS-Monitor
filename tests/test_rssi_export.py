from collections import deque
from datetime import datetime, timedelta

from ui.main_window import MainWindow


def select_vessel(window, mmsi, rssi_history=None):

    vessel = window.registry.get_or_create(mmsi)

    if rssi_history is not None:
        vessel.rssi_history = deque(rssi_history)

    window.selected_mmsi = mmsi
    window.show_vessel_details(vessel)

    return vessel


def test_export_button_disabled_with_no_vessel_selected(qapp):

    window = MainWindow()

    assert not window.export_rssi_button.isEnabled()


def test_export_button_enabled_once_a_vessel_is_selected(qapp):

    window = MainWindow()

    select_vessel(window, 111111111)

    assert window.export_rssi_button.isEnabled()


def test_export_button_disabled_again_on_deselect(qapp):

    window = MainWindow()

    select_vessel(window, 111111111)
    assert window.export_rssi_button.isEnabled()

    window.selected_mmsi = None
    window.clear_vessel_details()

    assert not window.export_rssi_button.isEnabled()


def test_export_button_disabled_while_rssi_section_is_collapsed(qapp):

    window = MainWindow()

    select_vessel(window, 111111111)
    assert window.export_rssi_button.isEnabled()

    window.rssi_toggle.setChecked(False)
    assert not window.export_rssi_button.isEnabled()

    window.rssi_toggle.setChecked(True)
    assert window.export_rssi_button.isEnabled()


def test_export_png_saves_a_grab_of_the_rssi_graph(qapp, monkeypatch, tmp_path):

    window = MainWindow()
    select_vessel(window, 111111111, rssi_history=[(datetime.now(), -70)])

    out_path = str(tmp_path / "rssi.png")
    monkeypatch.setattr(
        "ui.main_window.QFileDialog.getSaveFileName", lambda *a, **kw: (out_path, "PNG Image (*.png)")
    )

    window.export_rssi_png()

    assert (tmp_path / "rssi.png").exists()


def test_export_csv_current_view_writes_only_the_visible_window(qapp, monkeypatch, tmp_path):

    window = MainWindow()

    now = datetime(2026, 1, 1, 12, 0, 0)
    window.replay.current_time = now
    window.settings["track_length"] = "5"  # minutes

    history = [
        (now - timedelta(minutes=10), -80),  # outside the 5-minute window
        (now - timedelta(minutes=2), -70),
        (now, -65),
    ]

    select_vessel(window, 111111111, rssi_history=history)

    monkeypatch.setattr(window, "prompt_rssi_export_scope", lambda full_label: "current")

    out_path = str(tmp_path / "rssi.csv")
    monkeypatch.setattr(
        "ui.main_window.QFileDialog.getSaveFileName", lambda *a, **kw: (out_path, "CSV File (*.csv)")
    )

    window.export_rssi_csv()

    rows = (tmp_path / "rssi.csv").read_text(encoding="utf-8").strip().splitlines()

    assert rows[0] == "Timestamp,RSSI (dBm)"
    assert len(rows) == 3  # header + 2 in-window rows, the 10-minute-old one excluded


def test_export_csv_full_retained_in_live_mode_ignores_the_zoom_window(qapp, monkeypatch, tmp_path):

    window = MainWindow()

    now = datetime.now()
    window.replay.current_time = now  # RSSI zoom logic needs a time reference even outside a loaded file
    window.settings["track_length"] = "5"

    history = [(now - timedelta(minutes=10), -80), (now, -65)]

    select_vessel(window, 111111111, rssi_history=history)

    assert not window.replay.filename  # no file loaded -> Live-mode branch

    monkeypatch.setattr(window, "prompt_rssi_export_scope", lambda full_label: "full")

    out_path = str(tmp_path / "rssi.csv")
    monkeypatch.setattr(
        "ui.main_window.QFileDialog.getSaveFileName", lambda *a, **kw: (out_path, "CSV File (*.csv)")
    )

    window.export_rssi_csv()

    rows = (tmp_path / "rssi.csv").read_text(encoding="utf-8").strip().splitlines()

    assert len(rows) == 3  # header + both rows, including the one outside the 5-minute zoom window


def test_export_csv_cancelled_scope_writes_nothing(qapp, monkeypatch, tmp_path):

    window = MainWindow()
    select_vessel(window, 111111111, rssi_history=[(datetime.now(), -70)])

    monkeypatch.setattr(window, "prompt_rssi_export_scope", lambda full_label: None)

    saved = []
    monkeypatch.setattr("ui.main_window.QFileDialog.getSaveFileName", lambda *a, **kw: saved.append(1))

    window.export_rssi_csv()

    assert saved == []
    assert list(tmp_path.iterdir()) == []
