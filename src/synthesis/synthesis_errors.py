"""Errors raised while building or validating synthesis output."""


class SynthesisError(RuntimeError):
    """Synthesis failed; `error_code` feeds run_failed (PRD FR4, FR6)."""

    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


