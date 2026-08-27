class PSMTParser:

    def process(self, sentence):

        try:

            fields = sentence.split(",")

            if len(fields) < 11:
                return None

            return {
                "channel": fields[2],
                "rssi": int(fields[10])
            }

        except Exception as e:

            print(f"PSMT ERROR: {e}")

            return None