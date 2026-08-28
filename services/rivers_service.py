import shapefile


class RiversService:

    def __init__(self, shapefile_path):

        self.shapefile_path = shapefile_path

        self.rivers = []

    def load(self):

        self.rivers = []

        reader = shapefile.Reader(self.shapefile_path)

        for shape, record in zip(reader.shapes(), reader.records()):

            points = shape.points
            parts = list(shape.parts) + [len(points)]

            for i in range(len(parts) - 1):

                segment = points[parts[i]:parts[i + 1]]

                if len(segment) < 2:
                    continue

                lons = [p[0] for p in segment]
                lats = [p[1] for p in segment]

                self.rivers.append({
                    "points": segment,
                    "min_lon": min(lons),
                    "max_lon": max(lons),
                    "min_lat": min(lats),
                    "max_lat": max(lats),
                    "min_zoom": record["min_zoom"]
                })

        return self.rivers
