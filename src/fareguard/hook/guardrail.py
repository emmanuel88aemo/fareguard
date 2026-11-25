"""The port through which the hook asks whether a text may reach the model.

The hook depends on this contract only. `BedrockGuardrail` answers it with a
Bedrock Guardrail and `FakeGuardrail` answers it in tests.
"""

from typing import Protocol


class Guardrail(Protocol):
    """Something that judges one text."""

    def blocks(self, text: str) -> bool:
        """Return whether `text` is blocked.

        An implementation raises when it cannot judge the whole text. It never
        answers False for a text it did not check: the caller denies on any
        exception.
        """
