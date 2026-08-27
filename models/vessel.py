from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Vessel:
    mmsi: int

    name: str = ""
    callsign: str = ""

    lat: float | None = None
    lon: float | None = None

    sog: float | None = None
    cog: float | None = None

    heading: int | None = None

    range_nm: float | None = None
    bearing_deg: float | None = None

    last_rssi: int | None = None

    message_count: int = 0

    pinned: bool = False

    last_seen: datetime = field(default_factory=datetime.utcnow)

    track: list = field(default_factory=list)