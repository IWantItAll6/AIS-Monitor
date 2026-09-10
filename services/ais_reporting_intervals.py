# ITU-R M.1371 nominal reporting intervals for dynamic position reports, by
# station type and speed over ground. Source: ITU-R M.1371-5 Table 4 (via
# https://comarsystems.com/support-hub/what-are-ais-reporting-intervals/ and
# https://www.navcen.uscg.gov/ais-class-a-reports) — verified against the
# standard's own numbers, not guessed.
#
# Deliberately NOT modeled (same simplification scripts/generate_sample_log.py
# already makes, for the same reason): Class A's anchored/moored slow-down
# (3min at <=3kn while anchored/moored, vs. the 10s "0-14kn" rate used here)
# and the faster "actively changing course" rates for both classes. Detecting
# either from a receive-only stream would need nav_status/heading-delta
# tracking with its own approximation error, on top of the one this already
# carries (see file_analysis_service.py) — not worth compounding for now.
#
# Class B has two sub-types with different tables, and — this matters,
# corrected after initially assuming otherwise — BOTH are speed-based, not
# just Class A. They're distinguishable from the decoded message itself:
# msg_type 18 carries a `cs` flag (True = CS/Carrier-Sense unit, the cheap
# recreational kind; False = SOTDMA unit, which uses the same cadence as
# Class A but slower); msg_type 19 ("Extended Class B **CS** Position
# Report" — CS is in the name) has no such flag because it's always CS.

CLASS_A_MSG_TYPES = (1, 2, 3)
CLASS_B_MSG_TYPES = (18, 19)


def class_a_interval_seconds(speed_kn):

    if speed_kn > 23:
        return 2

    if speed_kn > 14:
        return 6

    return 10


def class_b_sotdma_interval_seconds(speed_kn):

    if speed_kn > 23:
        return 5

    if speed_kn > 14:
        return 15

    if speed_kn > 2:
        return 30

    return 180


def class_b_cs_interval_seconds(speed_kn):

    if speed_kn > 2:
        return 30

    return 180


def expected_interval_seconds(msg_type, cs_flag, speed_kn):
    """The nominal seconds-between-reports a station transmitting msg_type
    at speed_kn should be reporting at, per ITU-R M.1371 — or None if
    msg_type has no modeled reporting-rate rule (static/AtoN/base-station
    messages, or an unrecognized type), meaning "not comparable" rather
    than "unlimited"/zero.

    speed_kn of None is treated as 0 (stationary) — a report with no speed
    field, or a filtered-out sentinel value, shouldn't be excluded from the
    estimate entirely, and 0 is the conservative (slowest, most lenient)
    assumption.
    """

    speed_kn = speed_kn or 0

    if msg_type in CLASS_A_MSG_TYPES:
        return class_a_interval_seconds(speed_kn)

    if msg_type == 18:
        return class_b_cs_interval_seconds(speed_kn) if cs_flag else class_b_sotdma_interval_seconds(speed_kn)

    if msg_type == 19:
        return class_b_cs_interval_seconds(speed_kn)

    return None
