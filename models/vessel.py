from dataclasses import dataclass, field
from datetime import datetime
from collections import deque


@dataclass
class Vessel:
    mmsi: int

    name: str = ""
    callsign: str = ""
    type: str = ""

    lat: float | None = None
    lon: float | None = None

    sog: float | None = None
    cog: float | None = None
    heading: int | None = None

    rssi: int | None = None

    last_seen: datetime = field(default_factory=datetime.now)
    track: deque = field(default_factory=deque)

    pinned: bool = False

    # Captured for every vessel regardless of whether the UI currently shows
    # them — see nav_status (shown) vs. the rest (stored for a possible
    # future "choose extra fields" view).
    nav_status: str | None = None
    rot: float | None = None
    destination: str = ""
    draught: float | None = None
    imo: int | None = None
    length: int | None = None
    beam: int | None = None

    # Computed fresh each time update_target_tree() runs, not from AIS data.
    range: float | None = None
    bearing: float | None = None
