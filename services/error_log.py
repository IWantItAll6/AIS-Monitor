from pathlib import Path
from datetime import datetime


class ErrorLog:
    """Collects recoverable parser errors (malformed/unsupported sentences)
    for the running session, so they're visible somewhere even in the
    packaged app, which builds with console=False (see AISMonitor.spec) —
    a bare print() there goes nowhere. Distinct from crash_handler.py, which
    handles fatal uncaught exceptions, not routine per-sentence parse
    failures."""

    # Caps in-memory history so a long session with a persistently noisy
    # feed can't grow this unboundedly. The on-disk log below is never
    # trimmed — this only bounds what the in-app viewer holds at once.
    MAX_ENTRIES = 500

    def __init__(self, path="data/errors.log"):

        self.path = Path(path)
        self.entries = []

    def add(self, source, message, sentence=None):

        entry = {
            "time": datetime.now(),
            "source": source,
            "message": message,
            "sentence": sentence
        }

        self.entries.append(entry)

        if len(self.entries) > self.MAX_ENTRIES:
            self.entries.pop(0)

        self._write_to_disk(entry)

        return entry

    def _write_to_disk(self, entry):

        self.path.parent.mkdir(parents=True, exist_ok=True)

        line = f"[{entry['time'].strftime('%Y-%m-%d %H:%M:%S')}] {entry['source']}: {entry['message']}"

        if entry["sentence"]:
            line += f" | sentence: {entry['sentence']}"

        # Opened per-call rather than held open like SessionRecorder's
        # handle — parse errors are rare enough that open/append/close
        # overhead is a non-issue, and it avoids needing explicit
        # start()/stop() lifecycle management for something that can fire
        # at any time in either live or replay mode.
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def clear(self):

        self.entries = []
