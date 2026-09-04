from services.error_log import ErrorLog


def test_add_records_entry_and_writes_to_disk(tmp_path):

    log = ErrorLog(path=tmp_path / "errors.log")

    log.add("AIS", "boom", sentence="!AIVDM,garbage")

    assert len(log.entries) == 1
    assert log.entries[0]["source"] == "AIS"
    assert log.entries[0]["message"] == "boom"
    assert log.entries[0]["sentence"] == "!AIVDM,garbage"

    contents = (tmp_path / "errors.log").read_text(encoding="utf-8")

    assert "AIS: boom" in contents
    assert "!AIVDM,garbage" in contents


def test_add_without_sentence_omits_it_from_disk_line(tmp_path):

    log = ErrorLog(path=tmp_path / "errors.log")

    log.add("PSMT", "bad rssi field")

    contents = (tmp_path / "errors.log").read_text(encoding="utf-8")

    assert "PSMT: bad rssi field" in contents
    assert "sentence:" not in contents


def test_entries_are_capped_but_disk_log_keeps_everything(tmp_path):

    log = ErrorLog(path=tmp_path / "errors.log")
    log.MAX_ENTRIES = 3

    for i in range(5):
        log.add("AIS", f"error {i}")

    assert len(log.entries) == 3
    assert [e["message"] for e in log.entries] == ["error 2", "error 3", "error 4"]

    contents = (tmp_path / "errors.log").read_text(encoding="utf-8")

    assert contents.count("error ") == 5


def test_clear_empties_in_memory_entries(tmp_path):

    log = ErrorLog(path=tmp_path / "errors.log")

    log.add("AIS", "boom")
    log.clear()

    assert log.entries == []
