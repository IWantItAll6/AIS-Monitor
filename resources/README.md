# resources/

Real captured AIS/GNSS/PSMT field-test log files go here, in the same
`[YYYY-MM-DD HH:MM:SS.ffffff] <sentence>` format the app's replay mode
and live-session recording feature both use.

These files aren't committed to the repository (see `.gitignore`) since
they can bake in a real receiver's test location. `tests/test_replay_regression.py`
looks for two specific files here and skips those tests gracefully if
they're not present:

- `field_log_1.txt`
- `field_log_2.log`

If you have your own AIS/GNSS capture in the same format, drop it here
(any filename) and use **File > Open Replay...** to load it in the app.
