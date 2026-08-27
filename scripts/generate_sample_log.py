"""
Generates a fully synthetic AIS/GNSS/PSMT replay log for public test
fixtures. Every vessel name, MMSI, callsign, and position here is made up —
none of it is derived from the author's real field-test captures, and the
reference position is deliberately not their real test location. Safe to
commit and share.

Re-run this after changing the scenario; it overwrites
resources/sample_replay.log.
"""

from datetime import datetime, timedelta
from math import cos, sin, radians

from pyais.encode import encode_dict

OUTPUT_PATH = "resources/sample_replay.log"

# A generic open-water reference point, not the author's real test site.
CENTER_LAT = 50.00
CENTER_LON = -5.00

START_TIME = datetime(2026, 1, 1, 8, 0, 0)
DURATION_SECONDS = 180
STEP_SECONDS = 2

OWN_MMSI = 999000000

VESSELS = [
    {
        "mmsi": 999000001, "name": "SAMPLE VESSEL ONE", "callsign": "ZZ1001",
        "ship_type": 70, "lat": CENTER_LAT + 0.05, "lon": CENTER_LON - 0.10,
        "course": 90.0, "speed": 12.0
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
]


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


def generate():

    lines = []

    own_lat, own_lon = CENTER_LAT, CENTER_LON - 0.2
    own_course = 45.0
    own_speed = 5.0

    vessels = [dict(v) for v in VESSELS]

    static_sent = set()

    timestamp = START_TIME

    for step in range(0, DURATION_SECONDS, STEP_SECONDS):

        timestamp = START_TIME + timedelta(seconds=step)
        prefix = f"[{timestamp:%Y-%m-%d %H:%M:%S}.{timestamp.microsecond // 1000:03d}]"

        own_lat, own_lon = move(own_lat, own_lon, own_course, own_speed, STEP_SECONDS)

        for sentence in encode_dict({
            "type": 1, "mmsi": OWN_MMSI, "lat": own_lat, "lon": own_lon,
            "speed": own_speed, "course": own_course, "heading": int(own_course), "status": 0, "turn": 0
        }, sentence_type="VDO"):
            lines.append(f"{prefix} {sentence}")

        lines.append(f"{prefix} {gprmc(timestamp, own_lat, own_lon, own_speed, own_course)}")
        lines.append(f"{prefix} {gpgga(timestamp, own_lat, own_lon)}")

        for vessel in vessels:

            vessel["lat"], vessel["lon"] = move(
                vessel["lat"], vessel["lon"], vessel["course"], vessel["speed"], STEP_SECONDS
            )

            for sentence in encode_dict({
                "type": 1, "mmsi": vessel["mmsi"], "lat": vessel["lat"], "lon": vessel["lon"],
                "speed": vessel["speed"], "course": vessel["course"],
                "heading": int(vessel["course"]), "status": 0, "turn": 0
            }, sentence_type="VDM"):
                lines.append(f"{prefix} {sentence}")

            lines.append(f"{prefix} {psmt('A', -90 - (vessel['mmsi'] % 20))}")

            if vessel["mmsi"] not in static_sent:

                for sentence in encode_dict({
                    "type": 5, "mmsi": vessel["mmsi"], "shipname": vessel["name"],
                    "callsign": vessel["callsign"], "ship_type": vessel["ship_type"],
                    "destination": "SAMPLE PORT"
                }, sentence_type="VDM"):
                    lines.append(f"{prefix} {sentence}")

                static_sent.add(vessel["mmsi"])

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Wrote {len(lines)} lines to {OUTPUT_PATH}")


if __name__ == "__main__":
    generate()
