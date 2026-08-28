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

        "vessel_timeout": "10",
        "track_length": "10",

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

        try:
            with open(cls.SETTINGS_FILE, "r") as f:
                data = json.load(f)

            settings = cls.DEFAULTS.copy()
            settings.update(data)

            return settings

        except FileNotFoundError:

            return cls.DEFAULTS.copy()

    @classmethod
    def save(cls, settings):

        cls.SETTINGS_FILE.parent.mkdir(exist_ok=True)

        with open(cls.SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=4)