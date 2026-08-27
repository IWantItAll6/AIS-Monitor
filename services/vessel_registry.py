from datetime import datetime

class VesselRegistry:

    def __init__(self):

        self.vessels = {}

    def get_or_create(self, mmsi):

        return self.vessels.setdefault(
            mmsi,
            {
                "mmsi": mmsi,
                "name": "",
                "callsign": "",
                "type": "",
                "lat": None,
                "lon": None,
                "sog": None,
                "cog": None,
                "heading": None,
                "rssi": None,
                "last_seen": datetime.now(),
                "track": [],
                "pinned": False
            }
        )

    def get(self, mmsi):
        return self.vessels.get(mmsi)

    def all(self):
        return self.vessels.values()