from pyais import decode
from datetime import datetime

class AISParser:

    def __init__(self, registry):

        self.registry = registry

        # Multi-part messages (Type 5 static/voyage data — callsign, ship
        # type, destination — is almost always 2 fragments) need every
        # fragment passed to decode() together; buffer here until complete.
        self.pending_fragments = {}

    def assemble(self, sentence):

        fields = sentence.split(",")

        if len(fields) < 6:
            return None

        total = int(fields[1])

        if total == 1:
            return [sentence]

        frag_num = int(fields[2])
        seq_id = fields[3]
        channel = fields[4]

        key = (channel, seq_id)

        parts = self.pending_fragments.setdefault(key, {})
        parts[frag_num] = sentence

        if len(parts) < total:
            return None

        ordered = [parts[i] for i in range(1, total + 1)]

        del self.pending_fragments[key]

        return ordered

    def process(self, sentence, current_time):

        try:

            fragments = self.assemble(sentence)

            if fragments is None:
                return None

            msg = decode(*fragments)

            mmsi = getattr(msg, "mmsi", None)

            # 0 isn't a real MMSI — it's what an unconfigured/silent
            # transceiver's own AIVDO echo decodes to.
            if not mmsi:
                return None

            current_time = current_time or datetime.now()

            vessel = self.registry.get_or_create(mmsi)

            vessel["mmsi"] = mmsi
            vessel["last_seen"] = current_time

            if hasattr(msg, "lat") and hasattr(msg, "lon"):
                vessel["lat"] = msg.lat
                vessel["lon"] = msg.lon
                vessel["track"].append((current_time, msg.lat, msg.lon))

            # AIS reserves specific values to mean "not available" rather than
            # a real reading — pyais decodes them as-is, so filter here.
            if hasattr(msg, "speed"):
                vessel["sog"] = msg.speed if msg.speed < 102.3 else None

            if hasattr(msg, "course"):
                vessel["cog"] = msg.course if msg.course < 360 else None

            if hasattr(msg, "heading"):
                vessel["heading"] = msg.heading if msg.heading != 511 else None

            if hasattr(msg, "shipname"):
                vessel["name"] = msg.shipname

            if hasattr(msg, "callsign") and msg.callsign:
                vessel["callsign"] = msg.callsign

            # ship_type 0 is AIS's own "not available" value, same idea as
            # the speed/course/heading sentinels above. pyais usually decodes
            # this as a ShipType enum, but falls back to a plain int for some
            # message/field paths (e.g. an unset field's default value) —
            # handle both rather than assuming .name is always there.
            if hasattr(msg, "ship_type") and msg.ship_type:
                ship_type = msg.ship_type
                vessel["type"] = (
                    ship_type.name.replace("_", " ") if hasattr(ship_type, "name") else str(ship_type)
                )

            return vessel


        except Exception as e:

            if "Missing fragment numbers" not in str(e):
                print(f"AIS ERROR: {e}")
            return None