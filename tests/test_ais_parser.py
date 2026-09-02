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


def test_reused_seq_id_with_mismatched_fragments_is_discarded_not_spliced():

    # Found in review: without checking that the assembled fragment
    # numbers are actually 1..total (not just that there are `total` of
    # them), a dropped fragment plus seq_id reuse could silently splice
    # together fragments from two unrelated messages into one decode()
    # call.
    parser = make_parser()

    t = datetime(2026, 1, 1, 12, 0, 0)

    # Old 3-part message: fragment 2 never arrives (dropped).
    assert parser.assemble("!AIVDM,3,1,5,A,OLD1,0*00", t) is None
    assert parser.assemble("!AIVDM,3,3,5,A,OLD3,0*00", t) is None

    # New, unrelated 2-part message reuses the same (channel, seq_id) —
    # its fragment 1 overwrites the old slot's fragment 1, coincidentally
    # making len(parts) == 2 == the new message's total.
    result = parser.assemble("!AIVDM,2,1,5,A,NEW1,0*00", t)

    assert result is None
    assert ("A", "5") not in parser.pending_fragments


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


def test_ordinary_vessel_mmsi_not_misclassified(monkeypatch):

    parser = make_parser()

    fake_msg = SimpleNamespace(mmsi=235123456, msg_type=1)
    monkeypatch.setattr(ais_parser_module, "decode", lambda *a: fake_msg)

    vessel = parser.process("!AIVDM,1,1,,,dummy,0*00", None)

    assert vessel.station_type == "vessel"
