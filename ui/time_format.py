def format_age(seconds):
    """754 -> "12m ago". Deliberately coarser than
    file_analysis_service.format_duration (which keeps both hours and
    minutes, or minutes and seconds) — this label only needs to orient the
    viewer ("that end is a while back"), not give a precise reading, and
    staying to one unit keeps it short enough to fit a graph corner.
    Shared between RssiGraphWidget and VesselUptimeBar so their time axes
    read identically when stacked."""

    seconds = int(seconds)

    if seconds < 60:
        return f"{seconds}s ago"

    minutes = seconds // 60

    if minutes < 60:
        return f"{minutes}m ago"

    hours = minutes // 60

    return f"{hours}h ago"
