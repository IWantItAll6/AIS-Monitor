from datetime import datetime, timedelta
from types import SimpleNamespace

import parsers.ais_parser as ais_parser_module
from parsers.ais_parser import AISParser, FRAGMENT_TIMEOUT_SECONDS
from services.vessel_registry import VesselRegistry


def make_parser():

    return AISParser(VesselRegistry())


def test_sentinel_values_filtered_to_none(monkeypatch):

    parser = make_parser()

    fake_msg = SimpleNamespace(
        mmsi=111222333, lat=50.6, lon=-2.5,
        speed=102.3, course=360.0, heading=511, shipname="TESTER"
    )
    monkeypatch.setattr(ais_parser_module, "decode", lambda *a: fake_msg)

    vessel = parser.process("!AIVDM,1,1,,,dummy,0*00", None)

    assert vessel.sog is None
    assert vessel.cog is None
    assert vessel.heading is None


def test_zero_mmsi_is_filtered(monkeypatch):

    # An unconfigured/silent transceiver's own AIVDO echo decodes to mmsi=0,
    # not a real vessel identity.
    parser = make_parser()

    fake_msg = SimpleNamespace(mmsi=0, lat=50.6, lon=-2.5)
    monkeypatch.setattr(ais_parser_module, "decode", lambda *a: fake_msg)

    assert parser.process("!AIVDO,1,1,,,dummy,0*00", None) is None


def test_live_mode_gets_a_real_timestamp_when_none_supplied(monkeypatch):

    parser = make_parser()

    fake_msg = SimpleNamespace(mmsi=123456789)
    monkeypatch.setattr(ais_parser_module, "decode", lambda *a: fake_msg)

    vessel = parser.process("!AIVDM,1,1,,,dummy,0*00", None)

    assert vessel.last_seen is not None


def test_multipart_message_assembled_across_calls_real_sentences():

    # Real fragment pair pulled from the private field-test log — a Type 5
    # static/voyage message, which is exactly the message type that carries
    # callsign/ship type and is (almost) always split across 2 fragments.
    parser = make_parser()

    fragment_1 = "!AIVDM,2,1,7,A,53MC1b800000lphg@01@E986lpuH40000000000j1@43240Ht00PDTVH13hj,0*7C"
    fragment_2 = "!AIVDM,2,2,7,A,h0000000000,2*7B"

    assert parser.process(fragment_1, None) is None

    vessel = parser.process(fragment_2, None)

    assert vessel is not None
    assert vessel.callsign == "MNLK4"
    assert vessel.type == "PilotVessel"


def test_stale_fragment_buffer_is_pruned_not_kept_forever():

    # Found in review: pending_fragments had no expiry, so a permanently
    # dropped fragment left its (channel, seq_id) slot jammed forever —
    # seq_id only ranges 0-9, so it's expected to be reused by later,
    # unrelated messages.
    parser = make_parser()

    old_time = datetime(2026, 1, 1, 12, 0, 0)

    assert parser.assemble("!AIVDM,3,1,5,A,AAA,0*00", old_time) is None
    assert ("A", "5") in parser.pending_fragments

    later_time = old_time + timedelta(seconds=FRAGMENT_TIMEOUT_SECONDS + 1)

    frag1 = "!AIVDM,2,1,5,A,BBB,0*00"
    frag2 = "!AIVDM,2,2,5,A,CCC,0*00"

    assert parser.assemble(frag1, later_time) is None
    assert parser.assemble(frag2, later_time) == [frag1, frag2]


def test_incomplete_message_with_corrupted_fragment_number_is_discarded_not_spliced():

    # The completeness check (fragments 1..N all actually present, not just
    # that `total` fragments were received) has to catch a fragment set
    # that adds up to the right *count* by coincidence but isn't the right
    # *fragment numbers* — e.g. a corrupted frag_num digit on one sentence.
    parser = make_parser()

    t = datetime(2026, 1, 1, 12, 0, 0)

    assert parser.assemble("!AIVDM,3,1,5,A,AAA,0*00", t) is None
    assert parser.assemble("!AIVDM,3,3,5,A,CCC,0*00", t) is None

    # A corrupted frag_num digit (4 instead of 2) brings the fragment
    # count up to `total`, but fragment 2 was never actually received.
    result = parser.assemble("!AIVDM,3,4,5,A,DDD,0*00", t)

    assert result is None
    assert ("A", "5") not in parser.pending_fragments


def test_seq_id_reused_by_a_new_message_discards_the_abandoned_one():

    # Fragment 1 unambiguously starts a fresh message for a (channel,
    # seq_id) slot (seq_id only ranges 0-9, so reuse by an unrelated
    # message is expected) — an old, never-completed message left in that
    # slot must be discarded rather than merged into when that happens,
    # not kept around waiting for fragments that will never arrive.
    parser = make_parser()

    t = datetime(2026, 1, 1, 12, 0, 0)

    # Old 3-part message: fragment 2 never arrives (dropped/abandoned).
    assert parser.assemble("!AIVDM,3,1,5,A,OLD1,0*00", t) is None
    assert parser.assemble("!AIVDM,3,3,5,A,OLD3,0*00", t) is None

    # New, unrelated 2-part message reuses the same (channel, seq_id).
    assert parser.assemble("!AIVDM,2,1,5,A,NEW1,0*00", t) is None

    result = parser.assemble("!AIVDM,2,2,5,A,NEW2,0*00", t)

    assert result == ["!AIVDM,2,1,5,A,NEW1,0*00", "!AIVDM,2,2,5,A,NEW2,0*00"]


def test_ship_type_falls_back_to_raw_code_when_not_an_enum_member(monkeypatch):

    # pyais doesn't reliably decode ship_type as a ShipType enum for every
    # code (confirmed empirically against real data) — must not crash.
    parser = make_parser()

    fake_msg = SimpleNamespace(mmsi=1, ship_type=36)
    monkeypatch.setattr(ais_parser_module, "decode", lambda *a: fake_msg)

    vessel = parser.process("!AIVDM,1,1,,,dummy,0*00", None)

    assert vessel.type == "36"


def test_msg_type_4_classified_as_base_station(monkeypatch):

    parser = make_parser()

    fake_msg = SimpleNamespace(mmsi=2321654, msg_type=4, lat=50.6, lon=-2.5)
    monkeypatch.setattr(ais_parser_module, "decode", lambda *a: fake_msg)

    vessel = parser.process("!AIVDM,1,1,,,dummy,0*00", None)

    assert vessel.station_type == "base_station"
    assert vessel.type == "Base Station"


def test_msg_type_21_classified_as_aton_with_name_and_virtual_flag(monkeypatch):

    parser = make_parser()

    fake_msg = SimpleNamespace(
        mmsi=992351000, msg_type=21, lat=50.6, lon=-2.5,
        name="APPROACH BUOY", aid_type=SimpleNamespace(name="STARBOARD_HAND_MARK"),
        virtual_aid=True,
    )
    monkeypatch.setattr(ais_parser_module, "decode", lambda *a: fake_msg)

    vessel = parser.process("!AIVDM,1,1,,,dummy,0*00", None)

    assert vessel.station_type == "aton"
    assert vessel.name == "APPROACH BUOY"
    assert vessel.type == "STARBOARD HAND MARK"
    assert vessel.virtual_aid is True


def test_sart_mob_epirb_classified_by_mmsi_prefix(monkeypatch):

    parser = make_parser()

    for prefix, expected_type, expected_label in (
        (970, "sart", "SART"), (972, "mob", "MOB"), (974, "epirb", "EPIRB"),
    ):

        fake_msg = SimpleNamespace(mmsi=int(f"{prefix}123456"), msg_type=1)
        monkeypatch.setattr(ais_parser_module, "decode", lambda *a: fake_msg)

        vessel = parser.process("!AIVDM,1,1,,,dummy,0*00", None)

        assert vessel.station_type == expected_type
        assert vessel.type == expected_label


def test_position_not_available_sentinel_is_not_stored(monkeypatch):

    # Found in review: sog/cog/heading each have an explicit "not available"
    # sentinel check, but lat/lon (91.0/181.0) didn't — an unavailable fix
    # got stored and plotted/tracked as if it were real.
    parser = make_parser()

    fake_msg = SimpleNamespace(mmsi=111222333, lat=91.0, lon=181.0)
    monkeypatch.setattr(ais_parser_module, "decode", lambda *a: fake_msg)

    vessel = parser.process("!AIVDM,1,1,,,dummy,0*00", None)

    assert vessel.lat is None
    assert vessel.lon is None
    assert len(vessel.track) == 0


def test_turn_rate_direction_only_sentinels_filtered_to_none(monkeypatch):

    # Found in review: only -128 (NO_TI_DEFAULT) was filtered; +-127
    # ("turning fast, exact rate unknown") passed through as if it were a
    # literal measured turn rate.
    parser = make_parser()

    for turn_value in (-128, 127, -127):

        fake_msg = SimpleNamespace(mmsi=111222333, turn=turn_value)
        monkeypatch.setattr(ais_parser_module, "decode", lambda *a: fake_msg)

        vessel = parser.process("!AIVDM,1,1,,,dummy,0*00", None)

        assert vessel.rot is None

    fake_msg = SimpleNamespace(mmsi=111222333, turn=30)
    monkeypatch.setattr(ais_parser_module, "decode", lambda *a: fake_msg)

    vessel = parser.process("!AIVDM,1,1,,,dummy,0*00", None)

    assert vessel.rot == 30.0


def test_multipart_total_is_pinned_from_first_fragment():

    # Found in review: `total` was re-read from whichever fragment arrived
    # most recently rather than pinned from the first — a corrupted later
    # fragment reporting a smaller total could make an incomplete message
    # look complete and get spliced together prematurely.
    parser = make_parser()

    t = datetime(2026, 1, 1, 12, 0, 0)

    assert parser.assemble("!AIVDM,3,1,9,A,AAA,0*00", t) is None

    # Second fragment's own total field is corrupted to 2 instead of 3.
    assert parser.assemble("!AIVDM,2,2,9,A,BBB,0*00", t) is None

    assert parser.assemble("!AIVDM,3,3,9,A,CCC,0*00", t) == [
        "!AIVDM,3,1,9,A,AAA,0*00", "!AIVDM,2,2,9,A,BBB,0*00", "!AIVDM,3,3,9,A,CCC,0*00",
    ]


def test_ordinary_vessel_mmsi_not_misclassified(monkeypatch):

    parser = make_parser()

    fake_msg = SimpleNamespace(mmsi=235123456, msg_type=1)
    monkeypatch.setattr(ais_parser_module, "decode", lambda *a: fake_msg)

    vessel = parser.process("!AIVDM,1,1,,,dummy,0*00", None)

    assert vessel.station_type == "vessel"
