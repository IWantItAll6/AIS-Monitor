import shapefile


class PlacesService:

    def __init__(self, shapefile_path):

        self.shapefile_path = shapefile_path

        self.places = []

    def load(self):

        self.places = []

        reader = shapefile.Reader(self.shapefile_path)

        for record in reader.records():

            data = record.as_dict()

            # UK coverage comes from UkTownsService (GeoNames) instead — far
            # more detailed than this global dataset's ~50 UK entries.
            if data["adm0name"] == "United Kingdom":
                continue

            self.places.append({
                "name": data["name"],
                "lat": data["latitude"],
                "lon": data["longitude"],
                "min_zoom": data["min_zoom"]
            })

        return self.places
