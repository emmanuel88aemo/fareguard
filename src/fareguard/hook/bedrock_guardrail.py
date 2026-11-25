"""The guardrail port answered by a Bedrock Guardrail, through the ApplyGuardrail API.

The text is sent with the source INPUT, which is the side the prompt attack
filter evaluates. The answer is read strictly: only a response that says the
guardrail took no action and that it guarded every character counts as "not
blocked". Anything else that is not a plain intervention is an error, and the
hook denies on an error.
"""

from collections.abc import Mapping, Sequence
from typing import Literal, Protocol

from botocore.config import Config

INTERVENED = "GUARDRAIL_INTERVENED"
NO_ACTION = "NONE"

# The hook function has 10 seconds in all. One attempt of at most 2 + 6 seconds ends
# before that, so a guardrail that does not answer is an error the hook turns into a
# denial, not a function the harness has to give up on.
CLIENT_CONFIG = Config(connect_timeout=2, read_timeout=6, retries={"total_max_attempts": 1})


class GuardrailResponseError(Exception):
    """ApplyGuardrail answered with something that cannot be read as a verdict."""


class UnknownActionError(GuardrailResponseError):
    """The response names neither of the two actions the API documents."""

    def __init__(self) -> None:
        """Say what was expected, without repeating any text of the response."""
        super().__init__(f"the action of ApplyGuardrail must be {INTERVENED} or {NO_ACTION}")


class IncompleteCoverageError(GuardrailResponseError):
    """The response does not state that the guardrail assessed the whole text."""

    def __init__(self) -> None:
        """Say what was expected, without repeating any text of the response."""
        super().__init__(
            "ApplyGuardrail must report a coverage in which every text character was guarded"
        )


class ApplyGuardrailClient(Protocol):
    """The one operation of the bedrock-runtime client that is used."""

    def apply_guardrail(
        self,
        *,
        guardrailIdentifier: str,  # noqa: N803  # the parameter names of the AWS API
        guardrailVersion: str,  # noqa: N803
        source: Literal["INPUT", "OUTPUT"],
        content: Sequence[Mapping[str, Mapping[str, str]]],
    ) -> Mapping[str, object]:
        """Apply the guardrail to `content` and return the response of the API."""


class BedrockGuardrail:
    """One version of one Bedrock Guardrail."""

    def __init__(
        self, guardrail_id: str, guardrail_version: str, client: ApplyGuardrailClient
    ) -> None:
        """Keep the guardrail to apply and the bedrock-runtime client to call it with."""
        self._guardrail_id = guardrail_id
        self._guardrail_version = guardrail_version
        self._client = client

    def blocks(self, text: str) -> bool:
        """Return whether the guardrail intervened on `text`.

        Raises:
            UnknownActionError: if the response names no known action.
            IncompleteCoverageError: if the response does not state that
                every character was guarded.
            botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError:
                if the call fails, is throttled or times out.
        """
        response = self._client.apply_guardrail(
            guardrailIdentifier=self._guardrail_id,
            guardrailVersion=self._guardrail_version,
            source="INPUT",
            content=[{"text": {"text": text}}],
        )
        action = response.get("action")
        if action == INTERVENED:
            return True
        if action != NO_ACTION:
            raise UnknownActionError
        if not _guarded_every_character(response):
            raise IncompleteCoverageError
        return False


def _guarded_every_character(response: Mapping[str, object]) -> bool:
    """Whether the response reports that it guarded some text and left none of it out."""
    coverage = response.get("guardrailCoverage")
    characters = coverage.get("textCharacters") if isinstance(coverage, Mapping) else None
    if not isinstance(characters, Mapping):
        return False
    guarded, total = characters.get("guarded"), characters.get("total")
    return _is_count(guarded) and _is_count(total) and guarded == total


def _is_count(value: object) -> bool:
    # bool is a subclass of int, and True is not a number of characters.
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
