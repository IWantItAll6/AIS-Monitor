"""Runs the test suite reliably: the main suite in one process, then each
@pytest.mark.serial test in its own fresh process, one at a time.

A handful of tests measure real wall-clock time against a Qt event loop and
have been observed to fail intermittently only when the full ~90-test suite
runs back-to-back in a single pytest process (never on their own) — likely
leftover QTimers/QThreads from earlier tests' MainWindow instances stealing
event-loop time. Running them afterward in brand-new processes sidesteps
that entirely, since each starts with a clean interpreter and no leftover
Qt state from anything else.

Plain `pytest` still works fine for quick iteration on a subset of tests —
this script is for a full, reliable run (e.g. before a release).
"""

import subprocess
import sys


def run(args):

    print(f"\n$ {' '.join(args)}", flush=True)

    return subprocess.run([sys.executable, "-m", "pytest", *args]).returncode


def main():

    exit_code = run(["-m", "not serial"])

    serial_node_ids = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "serial", "--collect-only", "-q"],
        capture_output=True, text=True
    ).stdout.splitlines()

    # --collect-only -q lists one node id per line, then a blank line and a
    # summary line ("N tests collected") — keep only lines that look like
    # an actual node id (module.py::test_name).
    serial_node_ids = [line for line in serial_node_ids if "::" in line]

    for node_id in serial_node_ids:

        result = run([node_id])

        if result != 0:
            exit_code = result

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
