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