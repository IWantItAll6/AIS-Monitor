from datetime import datetime, timedelta

from pyais.encode import encode_dict

from services.message_stats import MessageCounter, MessageStatistics
from ui.main_window import MainWindow


T0 = datetime(2026, 9, 25, 12, 0, 0)


def at(seconds):

    return T0 + timedelta(seconds=seconds)


def test_rate_is_unknown_until_enough_time_has_passed():

    counter = MessageCounter(60)

    counter.record(at(0))

    # One message in the first second would otherwise read as 60/min.
    assert counter.rate_per_minute(at(1)) is None
    assert counter.count == 1


def test_rate_uses_elapsed_time_before_a_full_window():

    counter = MessageCounter(60)

    for s in range(0, 30, 3):  # 10 messages over 30s
        counter.record(at(s))

    assert counter.rate_per_minute(at(30)) == 20


def test_rate_only_counts_the_last_window():

    counter = MessageCounter(60)

    for s in range(0, 120):  # one a second for two minutes...
        counter.record(at(s))

    # ...then silence: the rate falls away as the window empties, while
    # the running total is kept.
    assert counter.rate_per_minute(at(120)) == 60
    assert counter.rate_per_minute(at(150)) == 30
    assert counter.rate_per_minute(at(200)) == 0
    assert counter.count == 120


def test_statistics_break_down_by_type_and_station_class():

    stats = MessageStatistics()

    for msg_type, mmsi in ((1, 235000001), (1, 235000001), (5, 235000001), (18, 235000002),
                           (24, 235000002), (4, 2320001), (21, 992350001), (8, 235000003)):
        stats.record(at(0), msg_type, mmsi)

    assert stats.total == 8

    breakdown = stats.type_breakdown()
    assert breakdown[0][:3] == (1, "Position report (Class A)", 2)
    assert breakdown[0][3] == 25

    # The msg 8 sender never said what it is, so it isn't counted.
    assert dict(stats.station_class_counts()) == {
        "Class A": 1, "Class B": 1, "Base station": 1, "SAR aircraft": 0, "Aid to Navigation": 1,
    }


def test_reset_clears_everything():

    stats = MessageStatistics()
    stats.record(at(0), 1, 235000001)

    stats.reset()

    assert stats.total == 0
    assert stats.type_breakdown() == []
    assert stats.rate_per_minute(at(30)) is None


def position_report(mmsi, msg_type=1):

    return encode_dict(
        {"type": msg_type, "mmsi": mmsi, "lat": 50.5, "lon": -2.3, "speed": 5, "course": 90},
        talker_id="AI", sentence_type="VDM"
    )[0]


def test_received_messages_are_counted_per_vessel_and_receiver_wide(qapp):

    window = MainWindow()

    for s in range(0, 60, 10):
        window.replay.current_time = at(s)
        window.route_sentence(position_report(235000001))

    window.route_sentence(position_report(235000002, msg_type=18))

    vessel = window.registry.get(235000001)

    assert vessel.message_counter.count == 6
    assert window.message_stats.total == 7

    item = window.tree_items[235000001]
    assert item.text(7) == "6"

    window.show_vessel_details(vessel)
    assert window.detail_messages.text() == "6"
    assert window.detail_message_rate.text().endswith("/min")


def test_own_ship_echo_is_not_counted(qapp):

    window = MainWindow()
    window.replay.current_time = at(0)

    window.route_sentence(position_report(235000001).replace("!AIVDM", "!AIVDO"))

    assert window.message_stats.total == 0


def test_clearing_the_session_resets_the_statistics(qapp):

    window = MainWindow()
    window.replay.current_time = at(0)
    window.route_sentence(position_report(235000001))

    window.reset_session()

    assert window.message_stats.total == 0


def test_message_columns_and_fields_are_hidden_by_default(qapp):

    window = MainWindow()

    assert window.target_tree.isColumnHidden(7)
    assert window.target_tree.isColumnHidden(8)
    assert window.detail_field_captions["Messages"].isHidden()
    assert window.detail_field_captions["Message Rate"].isHidden()


def test_status_bar_message_rate_toggle(qapp):

    window = MainWindow()

    assert "Messages:" not in window.status_bar.currentMessage()

    window.show_message_rate_action.setChecked(True)

    assert "Messages:" in window.status_bar.currentMessage()
    assert window.settings["show_message_rate"] is True


def test_message_stats_dialog_shows_current_counts(qapp):

    window = MainWindow()
    window.replay.current_time = at(0)
    window.route_sentence(position_report(235000001))

    window.show_message_stats()
    dialog = window.message_stats_dialog

    assert dialog.total_label.text() == "1"
    assert dialog.class_labels["Class A"].text() == "1"
    assert dialog.type_table.item(0, 1).text() == "Position report (Class A)"

    dialog.close()
