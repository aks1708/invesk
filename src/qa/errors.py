"""Errors raised while loading or answering from a saved run."""


class QAError(RuntimeError):
    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class QAResponseError(QAError):
    def __init__(self, message: str) -> None:
        super().__init__(message, error_code="qa_response_invalid")
