"""Interactive progress spinner shown while the run pipeline works.

The spinner animates on a background thread and is drawn only when stdout
is a tty (interactive runs); piped input and tests get a plain no-op, so
captured output is never polluted with spinner frames.
"""

import itertools
import threading
from typing import TextIO

#: Braille spinner frames.
FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
#: Seconds between frames.
INTERVAL = 0.1


class Spinner:
    """TTY-only animated spinner; a no-op when stdout is not a terminal."""

    def __init__(self, message: str, stdout: TextIO) -> None:
        self._message = message
        self._stdout = stdout
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _live(self) -> bool:
        try:
            return self._stdout.isatty()
        except Exception:
            return False

    def _spin(self) -> None:
        frames = itertools.cycle(FRAMES)
        while True:
            self._stdout.write(f"\r{next(frames)} {self._message}…")
            self._stdout.flush()
            if self._stop.wait(INTERVAL):
                return

    def __enter__(self) -> "Spinner":
        if self._live():
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join()
        self._stdout.write("\r\x1b[2K")  # erase the spinner line
        self._stdout.flush()


def spinner(message: str, stdout: TextIO) -> Spinner:
    """Message + stdout stream → a spinner context manager."""
    return Spinner(message, stdout)
