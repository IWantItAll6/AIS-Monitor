import pynmea2


class GNSSParser:

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
