from models.vessel import Vessel


class VesselRegistry:

    def __init__(self):

        self.vessels = {}

    def get_or_create(self, mmsi):

        return self.vessels.setdefault(mmsi, Vessel(mmsi))

    def get(self, mmsi):
        return self.vessels.get(mmsi)

    def all(self):
        return self.vessels.values()
