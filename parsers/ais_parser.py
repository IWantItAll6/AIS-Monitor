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


# SART/MOB/EPIRB beacons transmit ordinary Class A position reports (msg
# types 1-3) — there's no dedicated message type for them, so they're only
# identifiable by these reserved MMSI prefixes.
MMSI_PREFIX_STATION_TYPES = {
    "970": "sart",
    "972": "mob",
    "974": "epirb",
}

STATION_TYPE_LABELS = {
    "base_station": "Base Station",
    "sart": "SART",
    "mob": "MOB",
    "epirb": "EPIRB",
}


def classify_station(mmsi, msg_type):
    """Base stations and Aids to Navigation declare their category via
    msg_type (4 and 21 respectively); everything else is either a normal
    vessel or a safety beacon identifiable only by MMSI prefix."""

    if msg_type == 4:
        return "base_station"

    if msg_type == 21:
        return "aton"

    return MMSI_PREFIX_STATION_TYPES.get(str(mmsi)[:3], "vessel")


# Multi-part sentences normally complete within a couple of seconds;
# anything still incomplete after this long is a permanently dropped
# fragment (weak signal, interference), not a slow-arriving one.
FRAGMENT_TIMEOUT_SECONDS = 10


class AISParser:

    def __init__(self, registry):

        self.registry = registry

        # Multi-part messages (Type 5 static/voyage data — callsign, ship
        # type, destination — is almost always 2 fragments) need every
        # fragment passed to decode() together; buffer here until complete.
        # Keyed by (channel, seq_id) -> {"parts": {frag_num: sentence},
        # "first_seen": datetime}.
        self.pending_fragments = {}

    def assemble(self, sentence, current_time=None):

        fields = sentence.split(",")

        if len(fields) < 6:
            return None

        total = int(fields[1])

        if total == 1:
            return [sentence]

        frag_num = int(fields[2])
        seq_id = fields[3]
        channel = fields[4]

        now = current_time or datetime.now()

        self._prune_stale_fragments(now)

        key = (channel, seq_id)

        entry = self.pending_fragments.get(key)

        # Fragment 1 unambiguously starts a fresh message for this
        # (channel, seq_id) slot (ITU-R M.1371 fragments are always sent in
        # order) — so whatever was pending there before is either an
        # abandoned/dropped message or seq_id reuse by an unrelated one,
        # not a continuation of it. `total` is pinned from this fragment
        # and reused for the rest of the message, rather than re-read from
        # each later fragment's own field — a later fragment's total
        # disagreeing with the first (e.g. a corrupted digit) must not
        # change how many fragments this message is waited for.
        if entry is None or frag_num == 1:
            entry = {"parts": {}, "first_seen": now, "total": total}
            self.pending_fragments[key] = entry

        entry["parts"][frag_num] = sentence

        parts = entry["parts"]
        expected_total = entry["total"]

        if len(parts) < expected_total:
            return None

        # seq_id only ever ranges 0-9 (ITU-R M.1371), so it's expected to
        # be reused across genuinely unrelated messages. Without this
        # check, a dropped fragment leaving a stale entry behind could let
        # a later, unrelated message's fragment(s) silently complete it —
        # len(parts) == total by coincidence, but not with fragments 1..N
        # all actually present — splicing two different messages (possibly
        # from two different vessels) into one decode() call. Discarding
        # and starting clean is safer than guessing which fragments belong
        # together.
        if set(parts.keys()) != set(range(1, expected_total + 1)):
            del self.pending_fragments[key]
            return None

        ordered = [parts[i] for i in range(1, expected_total + 1)]

        del self.pending_fragments[key]

        return ordered

    def _prune_stale_fragments(self, now):

        stale_keys = [
            key for key, entry in self.pending_fragments.items()
            if (now - entry["first_seen"]).total_seconds() > FRAGMENT_TIMEOUT_SECONDS
        ]

        for key in stale_keys:
            del self.pending_fragments[key]

    def process(self, sentence, current_time):

        try:

            # Resolved before assemble() (which needs a real time to check
            # fragment-buffer staleness against), not after.
            current_time = current_time or datetime.now()

            fragments = self.assemble(sentence, current_time)

            if fragments is None:
                return None

            msg = decode(*fragments)

            mmsi = getattr(msg, "mmsi", None)

            # 0 isn't a real MMSI — it's what an unconfigured/silent
            # transceiver's own AIVDO echo decodes to.
            if not mmsi:
                return None

            vessel = self.registry.get_or_create(mmsi)

            vessel.mmsi = mmsi
            vessel.last_seen = current_time

            vessel.station_type = classify_station(mmsi, getattr(msg, "msg_type", None))

            if vessel.station_type == "aton":

                # Type 21 carries the AtoN's name directly (no shipname
                # field the way Class A/B static reports do), and its own
                # aid-type/virtual flag in place of a ship_type.
                if hasattr(msg, "name") and msg.name:
                    vessel.name = msg.name

                vessel.type = enum_label(getattr(msg, "aid_type", None)) or "Aid to Navigation"
                vessel.virtual_aid = bool(getattr(msg, "virtual_aid", False))

            elif vessel.station_type in STATION_TYPE_LABELS:
                vessel.type = STATION_TYPE_LABELS[vessel.station_type]

            # 91 / 181 is AIS's reserved "position not available" sentinel —
            # same idea as the sog/cog/heading sentinels filtered below, but
            # position had no such check, so an unavailable fix got stored
            # and plotted/tracked as if it were real.
            if hasattr(msg, "lat") and hasattr(msg, "lon") and msg.lat != 91 and msg.lon != 181:
                vessel.lat = msg.lat
                vessel.lon = msg.lon
                vessel.track.append((current_time, msg.lat, msg.lon))

            # AIS reserves specific values to mean "not available" rather than
            # a real reading — pyais decodes them as-is, so filter here.
            if hasattr(msg, "speed"):
                vessel.sog = msg.speed if msg.speed < 102.3 else None

            if hasattr(msg, "course"):
                vessel.cog = msg.course if msg.course < 360 else None

            if hasattr(msg, "heading"):
                vessel.heading = msg.heading if msg.heading != 511 else None

            if hasattr(msg, "shipname"):
                vessel.name = msg.shipname

            if hasattr(msg, "callsign") and msg.callsign:
                vessel.callsign = msg.callsign

            # ship_type 0 is AIS's own "not available" value, same idea as
            # the speed/course/heading sentinels above.
            if hasattr(msg, "ship_type") and msg.ship_type:
                vessel.type = enum_label(msg.ship_type)

            # Unlike ship_type, nav status 0 ("under way using engine") is a
            # real, common status, not a sentinel — no truthiness filter.
            if hasattr(msg, "status"):
                vessel.nav_status = enum_label(msg.status)

            if hasattr(msg, "turn"):
                # -128 (TurnRate.NO_TI_DEFAULT) means no turn info available;
                # +-127 means "turning right/left at more than 5deg/30s,
                # exact rate not available" — a direction-only indicator,
                # not a literal measured rate, same idea as -128.
                vessel.rot = None if msg.turn in (-128, 127, -127) else float(msg.turn)

            if hasattr(msg, "destination") and msg.destination:
                vessel.destination = msg.destination

            if hasattr(msg, "draught") and msg.draught:
                vessel.draught = msg.draught

            if hasattr(msg, "imo") and msg.imo:
                vessel.imo = msg.imo

            if hasattr(msg, "to_bow") and hasattr(msg, "to_stern"):
                if msg.to_bow or msg.to_stern:
                    vessel.length = msg.to_bow + msg.to_stern

            if hasattr(msg, "to_port") and hasattr(msg, "to_starboard"):
                if msg.to_port or msg.to_starboard:
                    vessel.beam = msg.to_port + msg.to_starboard

            return vessel


        except Exception as e:

            if "Missing fragment numbers" not in str(e):
                print(f"AIS ERROR: {e}")
            return None