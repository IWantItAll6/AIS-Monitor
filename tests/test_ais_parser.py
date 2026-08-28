from types import SimpleNamespace

import parsers.ais_parser as ais_parser_module
from parsers.ais_parser import AISParser
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


def test_ship_type_falls_back_to_raw_code_when_not_an_enum_member(monkeypatch):

    # pyais doesn't reliably decode ship_type as a ShipType enum for every
    # code (confirmed empirically against real data) — must not crash.
    parser = make_parser()

    fake_msg = SimpleNamespace(mmsi=1, ship_type=36)
    monkeypatch.setattr(ais_parser_module, "decode", lambda *a: fake_msg)

    vessel = parser.process("!AIVDM,1,1,,,dummy,0*00", None)

    assert vessel.type == "36"
