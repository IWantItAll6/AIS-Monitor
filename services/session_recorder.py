from pathlib import Path
from datetime import datetime


class SessionRecorder:

    def __init__(self, directory="data/recordings"):

        self.directory = Path(directory)

        self.file = None
        self.path = None

    def start(self):

        self.directory.mkdir(parents=True, exist_ok=True)

        filename = datetime.now().strftime("%Y-%m-%d_%H%M%S.log")

        self.path = self.directory / filename

        self.file = open(self.path, "a", encoding="utf-8")

    def write(self, line):

        if self.file:

            self.file.write(line + "\n")
            self.file.flush()

    def stop(self):

        if self.file:
            self.file.close()

        self.file = None
        self.path = None

    @property
    def is_recording(self):

        return self.file is not None

    def directory_size_mb(self):

        if not self.directory.exists():
            return 0

        total_bytes = sum(f.stat().st_size for f in self.directory.glob("*.log"))

        return total_bytes / (1024 * 1024)
