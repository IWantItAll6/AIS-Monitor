import pynmea2


class GNSSParser:
    """Accumulates state across sentences rather than returning a fresh
    reading per call — a GNSS receiver splits position and course across
    different sentence types (e.g. GGA for lat/lon, VTG for course), so
    self.position holds the latest known value of each field independently.
    """

    def __init__(self):

        self.position = {
            "lat": None,
            "lon": None,
            "fix": False,
            "cog": None
        }

    def process(self, sentence):

        try:

            msg = pynmea2.parse(sentence)

            if hasattr(msg, "latitude") and hasattr(msg, "longitude"):

                # Truthy check rather than "is not None": pynmea2 leaves
                # these as 0.0/"" when a sentence field is empty, not None.
                # Trade-off: a genuine fix exactly on the equator or prime
                # meridian would also be skipped here, but that's an
                # acceptable edge case for this app's use.
                if msg.latitude and msg.longitude:

                    self.position["lat"] = msg.latitude
                    self.position["lon"] = msg.longitude
                    self.position["fix"] = True

            # RMC carries true course, VTG carries true track — either is a
            # usable course-over-ground reading, whichever sentence arrives.
            course = getattr(msg, "true_course", None)

            if course in (None, ""):
                course = getattr(msg, "true_track", None)

            if course not in (None, ""):
                self.position["cog"] = float(course)

            return self.position

        except Exception:

            return None
