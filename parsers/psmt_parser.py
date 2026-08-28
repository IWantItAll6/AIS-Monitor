# $PSMT is a proprietary NMEA-0183-style sentence (the "$P" prefix is
# NMEA's own reserved namespace for manufacturer-specific extensions)
# emitted by a proprietary RX analyser unit the developer has access to.
# This parser was written by observing the sentence's plaintext output
# directly from that hardware — no vendor specification, NDA'd material,
# or other proprietary documentation was used or referenced. Support for
# this sentence exists purely for interoperability with that hardware.
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