"""Answer the hook events whose text reaches the model: screen that text with the guardrail.

"before_invocation" carries what the caller sent and "after_tool_call" carries
what a tool returned, which is where text planted in a ledger event arrives.
Text the guardrail blocks is denied with R7. Whatever keeps the whole text
from being checked is denied with R5: a context that is missing, truncated or
not shaped as expected, a guardrail that fails, and an event of any other name.

The guardrail is a second layer. No rule depends on it: a launch is still
judged by `decide` and by the tools, whatever the model was told.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import TypedDict

from fareguard.gate.models import RuleId
from fareguard.hook.decide import (
    ALLOWED_REASON,
    DENIAL_REASONS,
    MAX_RAW_TOOL_LENGTH,
    HookAnswer,
)
from fareguard.hook.guardrail import Guardrail
from fareguard.tool_names import normalise_tool_name

BEFORE_INVOCATION = "before_invocation"
AFTER_TOOL_CALL = "after_tool_call"
MAX_EVENT_NAME_LENGTH = 64

PASSED = "the guardrail did not block the text"
NOTHING_TO_CHECK = "the event holds no text to check"
BLOCKED = "the guardrail blocked the text"
UNKNOWN_EVENT = "the event is not one the hook answers"
TRUNCATED = "the context is truncated"
UNREADABLE = "the context does not have the expected shape"


class ScreenRecord(TypedDict):
    """One screened event as it is logged. It is never returned to the harness.

    `event` is the event name as it arrived, cut to MAX_EVENT_NAME_LENGTH
    characters. `raw_tool` is the tool name of an "after_tool_call" exactly as
    it arrived, cut to MAX_RAW_TOOL_LENGTH characters, and `tool` is the same
    without its gateway target. `detail` is one of the fixed sentences of this
    module, or None when an exception forced the denial; `error` is then the
    class name of that exception. No text of a message or of a tool result is
    recorded.
    """

    # The identifiers keep the spelling the harness uses, so a log line matches its event.
    hookEventId: str | None
    sessionId: str | None
    event: str | None
    tool: str | None
    raw_tool: str | None
    allowed: bool
    rule: RuleId | None
    detail: str | None
    error: str | None


@dataclass(frozen=True)
class ScreenResult:
    """The answer for the harness and the record to log."""

    answer: HookAnswer
    record: ScreenRecord


@dataclass(frozen=True)
class _Subject:
    """What was read from an event: who it is, and its text or why there is none.

    `text` is everything the event would show the model. It is None exactly
    when `problem` says why it could not be read.
    """

    hook_event_id: str | None = None
    session_id: str | None = None
    event: str | None = None
    raw_tool: str | None = None
    text: str | None = None
    problem: str | None = UNREADABLE


@dataclass(frozen=True)
class _Outcome:
    """The rule that denies, or None, and the fixed sentence that says why."""

    rule: RuleId | None
    detail: str | None


class _UnexpectedShapeError(Exception):
    """A part of the context is not what the documentation of the harness describes."""

    def __init__(self, problem: str = UNREADABLE) -> None:
        """Carry a fixed sentence only, never the part that was found."""
        super().__init__(problem)
        self.problem = problem


_UNREAD = _Subject()
_UNSCREENED = _Outcome("R5", None)


def read_event_name(event: object) -> str | None:
    """Return the name of the hook event, or None when `event` holds no name."""
    name = event.get("event") if isinstance(event, Mapping) else None
    return name if isinstance(name, str) else None


def screen(event: object, guardrail: Guardrail) -> ScreenResult:
    """Allow or deny `event` by the text it would show the model.

    Never raises, and calls the guardrail only when the whole text was read.
    A guardrail that raises or times out is answered with R5; the record then
    names the class of the exception.
    """
    subject = _UNREAD
    try:
        subject = _read_subject(event)
        outcome = _judge(subject, guardrail)
    # screen is the last step before the harness: whatever fails here must deny, not propagate.
    except Exception as error:  # noqa: BLE001
        return _result(subject, _UNSCREENED, type(error).__name__)
    return _result(subject, outcome)


def _judge(subject: _Subject, guardrail: Guardrail) -> _Outcome:
    if subject.text is None:
        return _Outcome("R5", subject.problem)
    # Blank text carries no instruction, and ApplyGuardrail has nothing to assess in it.
    if not subject.text.strip():
        return _Outcome(None, NOTHING_TO_CHECK)
    if guardrail.blocks(subject.text):
        return _Outcome("R7", BLOCKED)
    return _Outcome(None, PASSED)


def _read_subject(event: object) -> _Subject:
    if not isinstance(event, Mapping):
        return _UNREAD
    name, context = read_event_name(event), event.get("context")
    text, problem = _read_text(name, context)
    return _Subject(
        hook_event_id=_text(event.get("hookEventId")),
        session_id=_text(event.get("sessionId")),
        event=None if name is None else name[:MAX_EVENT_NAME_LENGTH],
        raw_tool=_read_raw_tool(name, context),
        text=text,
        problem=problem,
    )


def _read_raw_tool(name: str | None, context: object) -> str | None:
    """Return the tool name of an "after_tool_call" as it arrived, cut short."""
    if name != AFTER_TOOL_CALL or not isinstance(context, Mapping):
        return None
    tool = context.get("toolName")
    return tool[:MAX_RAW_TOOL_LENGTH] if isinstance(tool, str) else None


def _read_text(name: str | None, context: object) -> tuple[str | None, str | None]:
    """Return the text of the event and no problem, or no text and the problem."""
    if name not in (BEFORE_INVOCATION, AFTER_TOOL_CALL):
        return None, UNKNOWN_EVENT
    # The harness sets this key on the context of a "before_invocation" it shortened.
    if _is_truncated(context):
        return None, TRUNCATED
    try:
        parts = _message_texts(context) if name == BEFORE_INVOCATION else _tool_texts(context)
        return "\n".join(parts), None
    except _UnexpectedShapeError as error:
        return None, error.problem


def _is_truncated(value: object) -> bool:
    return isinstance(value, Mapping) and value.get("truncated") is True


def _message_texts(context: object) -> Iterator[str]:
    """Yield the text of every block of every message, in order.

    Raises:
        _UnexpectedShapeError: if a message is not a mapping with a list of
            blocks, or a block is anything but {"text": <text>}. A block of
            another kind, such as an image, cannot be checked as text.
    """
    for message in _list(_mapping(context).get("messages")):
        content = message.get("content") if isinstance(message, Mapping) else None
        for block in _list(content):
            if not isinstance(block, Mapping) or set(block) != {"text"}:
                raise _UnexpectedShapeError
            yield _required_text(block["text"])


def _tool_texts(context: object) -> Iterator[str]:
    """Yield every text of the tool result, and the error text when there is one.

    Raises:
        _UnexpectedShapeError: if a field was replaced with a truncation
            marker, the tool name is not text, the result is missing, the
            error is neither absent nor text, or the result holds a value
            that JSON does not have.
    """
    fields = _mapping(context)
    # The harness replaces a field that is too large with {"truncated": true, "preview": ...}.
    if any(_is_truncated(field) for field in fields.values()):
        raise _UnexpectedShapeError(TRUNCATED)
    _required_text(fields.get("toolName"))
    if "toolResult" not in fields:
        raise _UnexpectedShapeError
    yield from _texts_within(fields["toolResult"])
    if fields.get("error") is not None:
        yield _required_text(fields["error"])


def _texts_within(value: object) -> Iterator[str]:
    """Yield every text in a JSON value, keys included, whatever its shape.

    The documentation gives the tool result no schema, so nothing is assumed
    about where its text is.
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield _required_text(key)
            yield from _texts_within(item)
    elif isinstance(value, list):
        for item in value:
            yield from _texts_within(item)
    elif value is not None and not isinstance(value, bool | int | float):
        raise _UnexpectedShapeError


def _mapping(value: object) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise _UnexpectedShapeError
    return value


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise _UnexpectedShapeError
    return value


def _required_text(value: object) -> str:
    if not isinstance(value, str):
        raise _UnexpectedShapeError
    return value


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _result(subject: _Subject, outcome: _Outcome, error: str | None = None) -> ScreenResult:
    rule = outcome.rule
    answer: HookAnswer = (
        {"decision": "allow", "reason": ALLOWED_REASON}
        if rule is None
        else {"decision": "deny", "reason": DENIAL_REASONS[rule]}
    )
    record: ScreenRecord = {
        "hookEventId": subject.hook_event_id,
        "sessionId": subject.session_id,
        "event": subject.event,
        "tool": None if subject.raw_tool is None else normalise_tool_name(subject.raw_tool),
        "raw_tool": subject.raw_tool,
        "allowed": rule is None,
        "rule": rule,
        "detail": outcome.detail,
        "error": error,
    }
    return ScreenResult(answer, record)
