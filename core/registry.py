from models.vessel import Vessel


class VesselRegistry:

    def __init__(self):
        self.vessels = {}

    def get_or_create(self, mmsi: int):

        if mmsi not in self.vessels:
            self.vessels[mmsi] = Vessel(mmsi)

        return self.vessels[mmsi]

    def all_vessels(self):
        return list(self.vessels.values())