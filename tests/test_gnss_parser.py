from parsers.gnss_parser import GNSSParser


def test_rmc_extracts_position_and_cog():

    parser = GNSSParser()

    result = parser.process("$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A")

    assert result["fix"] is True
    assert result["cog"] == 84.4


def test_empty_course_field_does_not_crash_and_leaves_cog_none():

    parser = GNSSParser()

    # Shaped after a real sentence from a private field-test log (a
    # stationary receiver, so the course field is empty) — coordinates
    # replaced with synthetic values, checksum recomputed to match.
    result = parser.process("$GNRMC,115532.00,A,5007.40400,N,00534.06800,W,0.019,,180626,,,A,V*0A")

    assert result is not None
    assert result["cog"] is None


def test_invalid_sentence_returns_none():

    parser = GNSSParser()

    assert parser.process("not a valid nmea sentence") is None
