import json
from math import log10

MIN_ZOOM_FLOOR = 1.5
MIN_ZOOM_CEILING = 9.5


def population_to_min_zoom(population):

    # Continuous curve rather than population buckets: with fixed thresholds,
    # every town in a band (e.g. 100K-500K) gets the exact same min_zoom and
    # they all pop in simultaneously as soon as the zoom crosses that line —
    # looks fine one zoom step, a cluttered wall of labels the next. A smooth
    # curve means towns of similar size fade in at slightly different zooms
    # instead of all at once.
    raw = 18.0 - 2.3 * log10(max(population, 1))

    return max(MIN_ZOOM_FLOOR, min(MIN_ZOOM_CEILING, raw))


class UkTownsService:

    def __init__(self, towns_path):

        self.towns_path = towns_path

        self.places = []

    def load(self):

        with open(self.towns_path, encoding="utf-8") as f:
            towns = json.load(f)

        self.places = [
            {
                "name": town["name"],
                "lat": town["lat"],
                "lon": town["lon"],
                "min_zoom": population_to_min_zoom(town["population"])
            }
            for town in towns
        ]

        return self.places
