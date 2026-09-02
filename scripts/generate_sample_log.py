"""
Generates a fully synthetic AIS/GNSS/PSMT replay log for public test
fixtures. Every vessel name, MMSI, callsign, and position here is made up —
none of it is derived from the author's real field-test captures, and the
reference position is deliberately not their real test location. Safe to
commit and share.

Re-run this after changing the scenario; it overwrites
resources/sample_replay.log.
"""

import heapq
from datetime import datetime, timedelta
from itertools import count
from math import cos, sin, radians

from pyais.encode import encode_dict

OUTPUT_PATH = "resources/sample_replay.log"

# A generic open-water reference point, not the author's real test site.
CENTER_LAT = 50.00
CENTER_LON = -5.00

START_TIME = datetime(2026, 1, 1, 8, 0, 0)
DURATION_SECONDS = 180

# Simplified ITU-R M.1371 Table 3: how often a Class A unit repeats its own
# position report, by speed over ground. Doesn't model the anchored/moored
# (3 min) or actively-turning (faster) special cases — nothing in this
# scenario needs them, since every vessel here holds a constant course.
CLASS_A_REPORT_INTERVALS = [(14, 10), (23, 6)]  # (speed_kn upper bound, interval_s)
CLASS_A_FAST_INTERVAL = 2  # >23kn


def class_a_report_interval(speed_kn):

    for upper_bound, interval in CLASS_A_REPORT_INTERVALS:

        if speed_kn < upper_bound:
            return interval

    return CLASS_A_FAST_INTERVAL


# A real GNSS receiver outputs a fix at a steady ~1Hz regardless of how
# often any AIS traffic (own or others') happens to arrive.
GNSS_INTERVAL_SECONDS = 1

OWN_MMSI = 999000000

VESSELS = [
    {
        # Fast enough to fall in the 14-23kn bracket (6s reports) rather
        # than the same 10s bracket as the rest of the fleet below — so
        # the sample log actually demonstrates speed-dependent reporting,
        # not just a uniform interval that happens to be speed-aware.
        "mmsi": 999000001, "name": "SAMPLE VESSEL ONE", "callsign": "ZZ1001",
        "ship_type": 70, "lat": CENTER_LAT + 0.05, "lon": CENTER_LON - 0.10,
        "course": 90.0, "speed": 18.0
    },
    {
        "mmsi": 999000002, "name": "SAMPLE VESSEL TWO", "callsign": "ZZ1002",
        "ship_type": 60, "lat": CENTER_LAT - 0.03, "lon": CENTER_LON + 0.08,
        "course": 270.0, "speed": 8.5
    },
    {
        "mmsi": 999000003, "name": "SAMPLE TUG THREE", "callsign": "ZZ1003",
        "ship_type": 52, "lat": CENTER_LAT + 0.02, "lon": CENTER_LON + 0.02,
        "course": 180.0, "speed": 6.0
    },
    {
        "mmsi": 999000004, "name": "SAMPLE VESSEL FOUR", "callsign": "ZZ1004",
        "ship_type": 80, "lat": CENTER_LAT - 0.06, "lon": CENTER_LON - 0.04,
        "course": 315.0, "speed": 4.0
    },
]

# Base stations, AtoNs, and SART/MOB/EPIRB beacons are stationary and use
# their own AIS message types (or, for beacons, reserved MMSI prefixes) —
# kept separate from the moving VESSELS above since they're built and
# broadcast differently below.
BASE_STATION = {"mmsi": 2320000, "lat": CENTER_LAT + 0.08, "lon": CENTER_LON + 0.05}

ATONS = [
    {
        "mmsi": 992320001, "name": "SAMPLE LIGHTHOUSE", "aid_type": 1,
        "lat": CENTER_LAT + 0.10, "lon": CENTER_LON - 0.06, "virtual_aid": False
    },
    {
        "mmsi": 992320002, "name": "SAMPLE VIRTUAL MARK", "aid_type": 1,
        "lat": CENTER_LAT - 0.08, "lon": CENTER_LON - 0.02, "virtual_aid": True
    },
]

# SART/MOB/EPIRB beacons transmit ordinary Class A position reports; only
# their reserved MMSI prefix (970/972/974 — see parsers/ais_parser.py's
# MMSI_PREFIX_STATION_TYPES) identifies the station type.
BEACON = {"mmsi": 970000001, "name": "SAMPLE SART", "lat": CENTER_LAT + 0.01, "lon": CENTER_LON - 0.15}


def move(lat, lon, course_deg, speed_kn, seconds):

    distance_nm = speed_kn * seconds / 3600

    dlat = (distance_nm / 60) * cos(radians(course_deg))
    dlon = (distance_nm / 60) * sin(radians(course_deg)) / cos(radians(lat))

    return lat + dlat, lon + dlon


def nmea_checksum(body):

    checksum = 0

    for char in body:
        checksum ^= ord(char)

    return f"{checksum:02X}"


def to_nmea_lat(lat):

    hemisphere = "N" if lat >= 0 else "S"
    lat = abs(lat)
    degrees = int(lat)
    minutes = (lat - degrees) * 60

    return f"{degrees:02d}{minutes:07.4f}", hemisphere


def to_nmea_lon(lon):

    hemisphere = "E" if lon >= 0 else "W"
    lon = abs(lon)
    degrees = int(lon)
    minutes = (lon - degrees) * 60

    return f"{degrees:03d}{minutes:07.4f}", hemisphere


def gprmc(timestamp, lat, lon, speed_kn, course):

    time_str = timestamp.strftime("%H%M%S.00")
    date_str = timestamp.strftime("%d%m%y")

    lat_str, lat_hem = to_nmea_lat(lat)
    lon_str, lon_hem = to_nmea_lon(lon)

    body = (
        f"GPRMC,{time_str},A,{lat_str},{lat_hem},{lon_str},{lon_hem},"
        f"{speed_kn:.1f},{course:.1f},{date_str},,,A"
    )

    return f"${body}*{nmea_checksum(body)}"


def gpgga(timestamp, lat, lon):

    time_str = timestamp.strftime("%H%M%S.00")

    lat_str, lat_hem = to_nmea_lat(lat)
    lon_str, lon_hem = to_nmea_lon(lon)

    body = f"GPGGA,{time_str},{lat_str},{lat_hem},{lon_str},{lon_hem},1,08,0.9,10.0,M,48.0,M,,"

    return f"${body}*{nmea_checksum(body)}"


def psmt(channel, rssi):

    body = f"PSMT,VDI,{channel},1500,50,8,50,10,600,100,{rssi},4100,"

    return f"${body}*{nmea_checksum(body)}"


# Real multiplexed NMEA/AIS traffic doesn't arrive in one simultaneous
# burst — sentences trickle in a handful of milliseconds apart as each is
# actually received. When two entities happen to be scheduled at the exact
# same instant (e.g. everything at start-up), emit() nudges the later one
# forward by this much rather than stamping both identically.
LINE_SPACING_MS = 70


def generate():

    lines = []
    last_emitted = [None]

    def emit(sentence, at):

        if last_emitted[0] is not None and at <= last_emitted[0]:
            at = last_emitted[0] + timedelta(milliseconds=LINE_SPACING_MS)

        prefix = f"[{at:%Y-%m-%d %H:%M:%S}.{at.microsecond // 1000:03d}]"
        lines.append(f"{prefix} {sentence}")
        last_emitted[0] = at

    own = {"lat": CENTER_LAT, "lon": CENTER_LON - 0.2, "course": 45.0, "speed": 5.0}
    vessels = [dict(v) for v in VESSELS]

    # Base station, AtoNs, the beacon, and each vessel's Type 5 static data
    # (name/callsign/type — real receivers also send this far less often
    # than position reports) are all one-time, so they're emitted up front
    # rather than folded into the per-entity reporting schedule below.
    for sentence in encode_dict({
        "type": 4, "mmsi": BASE_STATION["mmsi"], "lat": BASE_STATION["lat"], "lon": BASE_STATION["lon"]
    }, sentence_type="VDM"):
        emit(sentence, START_TIME)

    for aton in ATONS:

        for sentence in encode_dict({
            "type": 21, "mmsi": aton["mmsi"], "aid_type": aton["aid_type"],
            "name": aton["name"], "lat": aton["lat"], "lon": aton["lon"],
            "virtual_aid": aton["virtual_aid"]
        }, sentence_type="VDM"):
            emit(sentence, START_TIME)

    for sentence in encode_dict({
        "type": 1, "mmsi": BEACON["mmsi"], "lat": BEACON["lat"], "lon": BEACON["lon"], "status": 14
    }, sentence_type="VDM"):
        emit(sentence, START_TIME)

    for vessel in vessels:

        for sentence in encode_dict({
            "type": 5, "mmsi": vessel["mmsi"], "shipname": vessel["name"],
            "callsign": vessel["callsign"], "ship_type": vessel["ship_type"],
            "destination": "SAMPLE PORT"
        }, sentence_type="VDM"):
            emit(sentence, START_TIME)

    # Everything from here on is scheduled as discrete events rather than
    # marched forward in lockstep — each vessel (and own-ship's GNSS vs. its
    # own AIS) keeps its own next-report time, advanced by its own interval
    # each time it fires, so a fast vessel's reports and a 1Hz GNSS fix
    # naturally interleave the way real independent transmitters would,
    # instead of everything being forced onto one shared cadence.
    sim_start = last_emitted[0] + timedelta(milliseconds=LINE_SPACING_MS)
    end_time = sim_start + timedelta(seconds=DURATION_SECONDS)

    seq = count()
    heap = [
        (sim_start, next(seq), "gnss", None),
        (sim_start, next(seq), "own_ais", None),
    ]

    for vessel in vessels:
        heap.append((sim_start, next(seq), "vessel_ais", vessel))

    heapq.heapify(heap)

    own_last_moved = sim_start
    vessel_last_moved = {vessel["mmsi"]: sim_start for vessel in vessels}

    while heap:

        time, _, kind, ref = heapq.heappop(heap)

        if time > end_time:
            break

        if kind == "gnss":

            elapsed = (time - own_last_moved).total_seconds()
            own["lat"], own["lon"] = move(own["lat"], own["lon"], own["course"], own["speed"], elapsed)
            own_last_moved = time

            emit(gprmc(time, own["lat"], own["lon"], own["speed"], own["course"]), time)
            emit(gpgga(time, own["lat"], own["lon"]), time)

            heapq.heappush(heap, (time + timedelta(seconds=GNSS_INTERVAL_SECONDS), next(seq), "gnss", None))

        elif kind == "own_ais":

            elapsed = (time - own_last_moved).total_seconds()
            own["lat"], own["lon"] = move(own["lat"], own["lon"], own["course"], own["speed"], elapsed)
            own_last_moved = time

            for sentence in encode_dict({
                "type": 1, "mmsi": OWN_MMSI, "lat": own["lat"], "lon": own["lon"], "speed": own["speed"],
                "course": own["course"], "heading": int(own["course"]), "status": 0, "turn": 0
            }, sentence_type="VDO"):
                emit(sentence, time)

            interval = class_a_report_interval(own["speed"])
            heapq.heappush(heap, (time + timedelta(seconds=interval), next(seq), "own_ais", None))

        elif kind == "vessel_ais":

            vessel = ref
            elapsed = (time - vessel_last_moved[vessel["mmsi"]]).total_seconds()
            vessel["lat"], vessel["lon"] = move(
                vessel["lat"], vessel["lon"], vessel["course"], vessel["speed"], elapsed
            )
            vessel_last_moved[vessel["mmsi"]] = time

            for sentence in encode_dict({
                "type": 1, "mmsi": vessel["mmsi"], "lat": vessel["lat"], "lon": vessel["lon"],
                "speed": vessel["speed"], "course": vessel["course"],
                "heading": int(vessel["course"]), "status": 0, "turn": 0
            }, sentence_type="VDM"):
                emit(sentence, time)

            emit(psmt("A", -90 - (vessel["mmsi"] % 20)), time)

            interval = class_a_report_interval(vessel["speed"])
            heapq.heappush(heap, (time + timedelta(seconds=interval), next(seq), "vessel_ais", vessel))

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Wrote {len(lines)} lines to {OUTPUT_PATH}")


if __name__ == "__main__":
    generate()
