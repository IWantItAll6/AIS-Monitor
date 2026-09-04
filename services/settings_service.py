import copy
import json
from pathlib import Path


class SettingsService:

    SETTINGS_FILE = Path("data/settings.json")

    DEFAULTS = {
        "ais_port": "",
        "ais_baud": "38400",

        "use_separate_gnss": False,

        "gnss_port": "",
        "gnss_baud": "115200",

        "ais_serial_format": "8N1",
        "gnss_serial_format": "8N1",

        "theme": "Dark",

        # NM (nautical miles) is the conventional abbreviation in marine
        # contexts — lowercase "nm" is ambiguous with nanometres in SI units.
        "distance_unit": "NM",

        # Default orange/gold pair, matching MapPanel's old hardcoded
        # colors. Pinned vessels also get a non-color ring around their
        # marker (see MapPanel.PIN_RING_COLOR) so the distinction doesn't
        # rely solely on these being visually distinct.
        "vessel_color": "#FF8C00",
        "pinned_color": "#FFD700",

        "vessel_timeout": "10",
        "track_length": "10",

        "show_place_names": True,
        "coastal_towns_only": False,
        "coastal_threshold_nm": "5",

        "last_replay_folder": "",
        "show_stale_targets": False,

        "recordings_folder": "data/recordings",

        # Data retention itself is the user's call — we only flag when the
        # recordings folder has grown large, never delete anything.
        "recordings_warning_size_mb": "500",

        # RSSI off by default — it's only meaningful with the specific RX
        # analyser unit, not a general AIS receiver setup.
        "visible_columns": {
            "Pinned": True,
            "MMSI": True,
            "Name": True,
            "Range": True,
            "Bearing": True,
            "RSSI": False,
            "Seen": True
        },

        # Every field in the details panel is independently toggleable
        # (View > Vessel Detail Fields). The originally-always-shown fields
        # default on; the ones added later (Destination onward) default off
        # since most users don't need them.
        "visible_detail_fields": {
            "MMSI": True,
            "Name": True,
            "Callsign": True,
            "Type": True,
            "Position": True,
            "SOG": True,
            "COG": True,
            "Heading": True,
            "Nav Status": True,
            "Range": True,
            "Bearing": True,
            "RSSI": True,
            "Seen": True,
            "Destination": False,
            "Draught": False,
            "IMO": False,
            "Rate of Turn": False,
            "Length": False,
            "Beam": False
        }
    }

    @classmethod
    def load(cls):

        # deepcopy, not copy(): a shallow copy still shares DEFAULTS' own
        # nested dicts (visible_columns, visible_detail_fields) by
        # reference. main_window.py mutates those in place (e.g.
        # settings.setdefault("visible_columns", {})[name] = visible), so
        # on a fresh install (no settings.json yet) that would silently
        # corrupt the class-level DEFAULTS for the rest of the process.
        settings = copy.deepcopy(cls.DEFAULTS)

        try:
            with open(cls.SETTINGS_FILE, "r") as f:
                data = json.load(f)

        except FileNotFoundError:
            return settings

        # A settings.json truncated/corrupted by a crash mid-write (see
        # save()) must not crash startup — fall back to defaults the same
        # as a missing file, rather than propagating JSONDecodeError.
        except json.JSONDecodeError:
            return settings

        for key, value in data.items():

            # Merge nested dicts key-by-key rather than replacing them
            # wholesale, so a settings.json saved before a new field was
            # added to visible_columns/visible_detail_fields (e.g. RSSI)
            # still picks up that field's documented default instead of
            # silently losing it — the whole-dict-replace this replaced
            # made an upgrading user see RSSI shown, not the intended
            # hidden-by-default.
            if isinstance(value, dict) and isinstance(settings.get(key), dict):
                settings[key].update(value)

            else:
                settings[key] = value

        return settings

    @classmethod
    def save(cls, settings):

        cls.SETTINGS_FILE.parent.mkdir(exist_ok=True)

        # Write-then-rename rather than writing SETTINGS_FILE directly: a
        # crash/power-loss mid-write to the real file leaves it truncated,
        # and json.load() on a truncated file raises JSONDecodeError on the
        # next launch. os.replace() is atomic, so the real file is always
        # either the old complete version or the new complete version, never
        # a partial write.
        tmp_path = cls.SETTINGS_FILE.with_suffix(".json.tmp")

        with open(tmp_path, "w") as f:
            json.dump(settings, f, indent=4)

        tmp_path.replace(cls.SETTINGS_FILE)