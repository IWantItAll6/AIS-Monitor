def format_duration_short(seconds):
    """754 -> "12m". Deliberately coarser than
    file_analysis_service.format_duration (which keeps both hours and
    minutes, or minutes and seconds) — callers only need to orient the
    viewer ("that end is a while back", "you're viewing a 5m window"), not
    give a precise reading, and staying to one unit keeps it short enough
    to fit a graph corner or a small zoom-level label."""

    seconds = int(seconds)

    if seconds < 60:
        return f"{seconds}s"

    minutes = seconds // 60

    if minutes < 60:
        return f"{minutes}m"

    hours = minutes // 60

    return f"{hours}h"


def format_age(seconds):
    """754 -> "12m ago" — see format_duration_short. Shared between
    RssiGraphWidget and VesselUptimeBar so their time axes read identically
    when stacked."""

    return f"{format_duration_short(seconds)} ago"
