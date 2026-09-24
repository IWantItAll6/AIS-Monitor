from services.geo import NM_PER_UNIT


def range_limit_nm(limit, unit):
    """The Range Limit setting (a number in the user's chosen distance unit,
    0 meaning Off) converted to nautical miles — the unit vessel.range is
    always stored in — or None when the limit is off."""

    try:
        limit = float(limit)

    except (TypeError, ValueError):
        return None

    if limit <= 0:
        return None

    return limit / NM_PER_UNIT.get(unit, 1.0)


def within_range_limit(vessel, limit_nm):
    """Whether a vessel should be shown under the Range Limit. Only hides
    vessels positively known to be beyond it — no own-ship fix, or no
    position for the vessel, means no range to judge by, so it stays
    visible rather than silently disappearing. Pinned vessels are always
    shown: pinning is an explicit "keep following this one"."""

    if limit_nm is None or vessel.pinned or vessel.range is None:
        return True

    return vessel.range <= limit_nm


def convert_range_limit(limit, from_unit, to_unit):
    """Re-expresses a Range Limit value when the distance unit changes, so
    the limit keeps meaning (roughly) the same distance instead of silently
    becoming e.g. 60 km instead of 60 NM. Rounded to the nearest 10 — the
    Preferences spin box's step — and never rounded down to 0 (Off)."""

    if limit <= 0:
        return 0

    limit_nm = limit / NM_PER_UNIT.get(from_unit, 1.0)
    converted = limit_nm * NM_PER_UNIT.get(to_unit, 1.0)

    return max(10, int(round(converted / 10.0)) * 10)
