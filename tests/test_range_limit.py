import copy

from services.range_limit import convert_range_limit, range_limit_nm, within_range_limit
from services.settings_service import SettingsService
from ui.main_window import MainWindow
from ui.preferences_dialog import PreferencesDialog


class FakeVessel:

    def __init__(self, range_nm, pinned=False):
        self.range = range_nm
        self.pinned = pinned


def test_range_limit_nm_converts_from_display_unit_and_zero_means_off():

    assert range_limit_nm(60, "NM") == 60
    assert range_limit_nm(0, "NM") is None
    assert range_limit_nm("junk", "NM") is None
    assert abs(range_limit_nm(111.12, "Km") - 60) < 0.01


def test_within_range_limit_hides_only_vessels_known_to_be_too_far():

    assert within_range_limit(FakeVessel(59), 60)
    assert not within_range_limit(FakeVessel(61), 60)

    # Unknown range (no own fix / no vessel position) stays visible, pinned
    # always stays visible, and no limit shows everything.
    assert within_range_limit(FakeVessel(None), 60)
    assert within_range_limit(FakeVessel(200, pinned=True), 60)
    assert within_range_limit(FakeVessel(200), None)


def test_convert_range_limit_keeps_roughly_the_same_distance():

    assert convert_range_limit(60, "NM", "Km") == 110
    assert convert_range_limit(110, "Km", "NM") == 60
    assert convert_range_limit(0, "NM", "Km") == 0

    # Never rounds a real limit down to 0, which would mean Off.
    assert convert_range_limit(10, "Km", "NM") == 10


def make_window_with_vessels():

    window = MainWindow()
    window.settings["range_limit"] = 60
    window.settings["distance_unit"] = "NM"

    window.own_position.update({"fix": True, "lat": 50.0, "lon": 0.0})

    near = window.registry.get_or_create(111)
    near.lat, near.lon = 50.5, 0.0  # ~30 NM

    far = window.registry.get_or_create(222)
    far.lat, far.lon = 52.0, 0.0  # ~120 NM

    far_pinned = window.registry.get_or_create(333)
    far_pinned.lat, far_pinned.lon = 52.0, 0.5
    far_pinned.pinned = True

    window.registry.get_or_create(444)  # no position yet

    return window


def test_range_limit_hides_far_vessels_from_map_and_list(qapp):

    window = make_window_with_vessels()

    window.update_target_tree()

    assert {v.mmsi for v in window.map_view.vessels} == {111, 333, 444}
    assert window.tree_items[222].isHidden()
    assert not any(window.tree_items[m].isHidden() for m in (111, 333, 444))
    assert window.targets_label.text() == "Targets (3 of 4)"

    # Search still works on top of the range filter, and can't un-hide an
    # out-of-range vessel.
    window.target_search.setText("222")
    window.apply_target_filter()
    assert window.tree_items[222].isHidden()


def test_range_limit_off_or_no_fix_shows_everything(qapp):

    window = make_window_with_vessels()

    window.settings["range_limit"] = 0
    window.update_target_tree()

    assert len(window.map_view.vessels) == 4
    assert window.targets_label.text() == "Targets (4)"

    window.settings["range_limit"] = 60
    window.own_position["fix"] = False
    window.update_target_tree()

    assert len(window.map_view.vessels) == 4
    assert not window.tree_items[222].isHidden()


def test_preferences_range_limit_follows_distance_unit(qapp):

    settings = copy.deepcopy(SettingsService.DEFAULTS)

    dialog = PreferencesDialog(settings)

    assert dialog.range_limit.value() == 60
    assert dialog.range_limit.suffix() == " NM"
    assert dialog.range_limit.singleStep() == 10

    dialog.distance_unit.setCurrentText("Km")

    assert dialog.range_limit.value() == 110
    assert dialog.range_limit.suffix() == " km"

    dialog.range_limit.setValue(0)
    assert dialog.range_limit.text() == "Off"

    dialog.save_settings()
    assert settings["range_limit"] == 0
    assert settings["distance_unit"] == "Km"
