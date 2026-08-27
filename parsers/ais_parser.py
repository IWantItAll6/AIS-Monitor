from pyais import decode
from datetime import datetime


def enum_label(value):
    """pyais decodes several fields (ship_type, status) as enums most of the
    time, but not reliably for every code — confirmed empirically against
    real data. Falls back to the raw value's string rather than assuming
    .name is always present."""

    if value is None:
        return None

    return value.name.replace("_", " ") if hasattr(value, "name") else str(value)


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
            # the speed/course/heading sentinels above.
            if hasattr(msg, "ship_type") and msg.ship_type:
                vessel["type"] = enum_label(msg.ship_type)

            # Unlike ship_type, nav status 0 ("under way using engine") is a
            # real, common status, not a sentinel — no truthiness filter.
            if hasattr(msg, "status"):
                vessel["nav_status"] = enum_label(msg.status)

            if hasattr(msg, "turn"):
                # -128 (TurnRate.NO_TI_DEFAULT) means no turn info available.
                vessel["rot"] = None if msg.turn == -128 else float(msg.turn)

            if hasattr(msg, "destination") and msg.destination:
                vessel["destination"] = msg.destination

            if hasattr(msg, "draught") and msg.draught:
                vessel["draught"] = msg.draught

            if hasattr(msg, "imo") and msg.imo:
                vessel["imo"] = msg.imo

            if hasattr(msg, "to_bow") and hasattr(msg, "to_stern"):
                if msg.to_bow or msg.to_stern:
                    vessel["length"] = msg.to_bow + msg.to_stern

            if hasattr(msg, "to_port") and hasattr(msg, "to_starboard"):
                if msg.to_port or msg.to_starboard:
                    vessel["beam"] = msg.to_port + msg.to_starboard

            return vessel


        except Exception as e:

            if "Missing fragment numbers" not in str(e):
                print(f"AIS ERROR: {e}")
            return None