"""Interactive-only spinner behavior (constitution P3: no output pollution).

The spinner animates only when stdout is a tty; piped runs and tests see a
no-op that never writes frames.
"""

import pytest

from src.cli.spinner import spinner


class FakeTty:
    """Collects writes and reports itself as a terminal."""

    def __init__(self) -> None:
        self.chunks: list[str] = []

    def isatty(self) -> bool:
        return True

    def write(self, text: str) -> int:
        self.chunks.append(text)
        return len(text)

    def flush(self) -> None:
        pass

    def text(self) -> str:
        return "".join(self.chunks)


class FakeStream:
    """A non-tty stream, like the StringIO streams tests inject."""

    def __init__(self) -> None:
        self.chunks: list[str] = []

    def isatty(self) -> bool:
        return False

    def write(self, text: str) -> int:
        self.chunks.append(text)
        return len(text)

    def flush(self) -> None:
        pass

    def text(self) -> str:
        return "".join(self.chunks)


def test_spinner_is_a_no_op_on_a_non_tty_stdout():
    stream = FakeStream()

    with spinner("Cooking", stream) as value:
        assert value is not None  # the body still runs

    assert stream.text() == ""


def test_spinner_draws_frames_and_clears_the_line_on_a_tty():
    stream = FakeTty()

    with spinner("Cooking", stream):
        pass

    written = stream.text()
    assert "Cooking…" in written
    assert written.endswith("\r\x1b[2K")  # the spinner line is erased


def test_spinner_stops_cleanly_after_the_block():
    stream = FakeTty()

    with spinner("Cooking", stream):
        pass  # the join happens on exit; the test returning proves it

    # All frame writes happened before the erase, nothing follows it.
    assert stream.text().count("\r\x1b[2K") == 1


@pytest.mark.parametrize("isatty_result", [True, False])
def test_spinner_tolerates_streams_that_raise_on_isatty(isatty_result):
    class BrokenStream:
        def isatty(self) -> bool:
            raise RuntimeError("no stream")

        def write(self, text: str) -> int:
            raise AssertionError("a broken stream must never be written to")

        def flush(self) -> None:
            pass

    with spinner("Cooking", BrokenStream()):
        pass  # entering and leaving must not raise


# --- pipeline wiring: the report prints only after the spinner clears ----------


def test_pipeline_clears_the_spinner_before_printing_the_report(monkeypatch):
    """The Cooking line is erased first; the report must not race it."""
    from src.cli import pipeline
    from src.cli.config import EXIT_OK

    stream = FakeTty()

    def fake_stages(*args, **kwargs):
        return EXIT_OK, "REPORT TEXT"

    monkeypatch.setattr(pipeline, "_run_stages", fake_stages)
    status = pipeline._run_pipeline(
        run_input=None,
        events=None,
        yf=None,
        run_dir=None,
        config=None,
        api_key=None,
        exa_factory=None,
        ollama_client_factory=None,
        report_writer=None,
        clock=None,
        stdout=stream,
    )

    assert status == EXIT_OK
    written = stream.text()
    assert written.index("\r\x1b[2K") < written.index("REPORT TEXT")
    assert "Cooking" not in written.rsplit("\r\x1b[2K", 1)[-1]


def test_pipeline_prints_no_report_after_a_failed_run(monkeypatch):
    from src.cli import pipeline
    from src.cli.config import EXIT_RUNTIME_FAILURE

    stream = FakeTty()

    def fake_stages(*args, **kwargs):
        return EXIT_RUNTIME_FAILURE, None

    monkeypatch.setattr(pipeline, "_run_stages", fake_stages)
    status = pipeline._run_pipeline(
        run_input=None,
        events=None,
        yf=None,
        run_dir=None,
        config=None,
        api_key=None,
        exa_factory=None,
        ollama_client_factory=None,
        report_writer=None,
        clock=None,
        stdout=stream,
    )

    assert status == EXIT_RUNTIME_FAILURE
    written = stream.text()
    assert written.endswith("\r\x1b[2K")  # spinner cleared, nothing follows
    assert "REPORT" not in written
