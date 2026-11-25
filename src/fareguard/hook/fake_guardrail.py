"""A guardrail that needs no AWS, for tests and local runs."""

from collections.abc import Iterable


class FakeGuardrail:
    """Blocks a text that contains one of the given phrases, and records every text it saw.

    When built with `error`, every call raises it instead, as a guardrail that
    cannot be reached would.
    """

    def __init__(self, blocked_phrases: Iterable[str] = (), error: Exception | None = None) -> None:
        """Keep the phrases to block and the error to raise, if any."""
        self._blocked_phrases = tuple(blocked_phrases)
        self._error = error
        self.seen: list[str] = []

    def blocks(self, text: str) -> bool:
        """Return whether `text` contains a blocked phrase.

        Raises:
            Exception: the error the fake was built with, if any.
        """
        self.seen.append(text)
        if self._error is not None:
            raise self._error
        return any(phrase in text for phrase in self._blocked_phrases)
