from services.settings_service import SettingsService


def test_load_without_a_settings_file_does_not_share_defaults_nested_dicts(tmp_path, monkeypatch):

    # Found in review: SettingsService.load() used a shallow DEFAULTS.copy(),
    # so on a fresh install (no settings.json), settings["visible_columns"]
    # was the exact same dict object as the class-level DEFAULTS — mutating
    # it (as set_column_visible() does, in place) permanently corrupted
    # DEFAULTS for the rest of the process.
    monkeypatch.setattr(SettingsService, "SETTINGS_FILE", tmp_path / "does_not_exist.json")

    settings = SettingsService.load()
    settings["visible_columns"]["RSSI"] = True

    assert SettingsService.DEFAULTS["visible_columns"]["RSSI"] is False


def test_load_fills_in_a_nested_key_missing_from_an_older_settings_file(tmp_path, monkeypatch):

    # An on-disk settings.json saved before "RSSI" existed in
    # visible_columns shouldn't lose every *other* documented nested
    # default just because that one key is absent — merge per-key rather
    # than replacing the whole nested dict wholesale.
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        '{"visible_columns": {"Pinned": true, "MMSI": true, "Name": false}}'
    )
    monkeypatch.setattr(SettingsService, "SETTINGS_FILE", settings_file)

    settings = SettingsService.load()

    # Present in the file: the user's actual saved choice wins.
    assert settings["visible_columns"]["Name"] is False

    # Missing from the file (added to DEFAULTS after this file was saved):
    # falls back to the documented default, not silently dropped.
    assert settings["visible_columns"]["RSSI"] is False
    assert settings["visible_columns"]["Seen"] is True


def test_load_still_applies_top_level_overrides(tmp_path, monkeypatch):

    settings_file = tmp_path / "settings.json"
    settings_file.write_text('{"theme": "Light", "vessel_timeout": "30"}')
    monkeypatch.setattr(SettingsService, "SETTINGS_FILE", settings_file)

    settings = SettingsService.load()

    assert settings["theme"] == "Light"
    assert settings["vessel_timeout"] == "30"
    assert settings["distance_unit"] == SettingsService.DEFAULTS["distance_unit"]
