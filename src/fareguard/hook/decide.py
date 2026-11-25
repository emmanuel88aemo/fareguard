"""Answer one hook event of the harness with allow or deny.

The harness invokes the hook before every tool call. The model cannot call it
or influence it, and the reason it returns goes back to the model. A reason is
therefore a fixed sentence chosen by the rule that denied: it never repeats
text from the event, and the log record never holds the arguments of the call.
"""

import contextlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypedDict, TypeGuard

from fareguard.gate.evaluate import evaluate
from fareguard.gate.models import Limits, RuleId, ToolCall
from fareguard.ledger.store import LedgerStore

BEFORE_TOOL_CALL = "before_tool_call"
MAX_REASON_LENGTH = 1024
TARGET_SEPARATOR = "___"

ALLOWED_REASON = "allowed"
DENIAL_REASONS: Mapping[RuleId, str] = {
    "R1": "R1: the requested tool does not exist",
    "R2": "R2: the launch would exceed the spend cap of its disc",
    "R3": "R3: the launch would exceed the monthly spend cap",
    "R4": (
        "R4: the launch needs an approval that is approved, unused, issued for "
        "this disc and covers the estimated cost"
    ),
    "R5": "R5: the call is malformed, incomplete or could not be evaluated",
}


class HookAnswer(TypedDict):
    """What the harness expects back from the hook."""

    decision: Literal["allow", "deny"]
    reason: str


class HookRecord(TypedDict):
    """One decision as it is logged. It never holds the arguments of the call.

    `error` is the class name of an exception that forced the denial, or None.
    """

    # The identifiers keep the spelling the harness uses, so a log line matches its event.
    hookEventId: str | None
    sessionId: str | None
    tool: str | None
    allowed: bool
    rule: RuleId | None
    error: str | None


@dataclass(frozen=True)
class HookResult:
    """The answer for the harness and the record to log."""

    answer: HookAnswer
    record: HookRecord


@dataclass(frozen=True)
class _Request:
    """What was read from an event. `call` is None when the event holds no usable tool call."""

    hook_event_id: str | None = None
    session_id: str | None = None
    call: ToolCall | None = None


_UNREAD = _Request()


def normalise_tool_name(name: str) -> str:
    """Return the tool name without the gateway target: what follows the last "___"."""
    # ASSUMPTION, to confirm at deploy time: the gateway prefixes a tool name with its
    # target as "<target>___<tool>". This function is the only place that knows the format.
    return name.rpartition(TARGET_SEPARATOR)[2]


def decide(event: object, store: LedgerStore, limits: Limits, now: datetime) -> HookResult:
    """Allow or deny the tool call in `event`, given the ledger in `store` at the time `now`.

    Never raises. An event that is not a complete "before_tool_call", or whose
    tool input is missing, truncated or not a mapping, is denied with R5. So
    is a call that cannot be evaluated because the store or the gate failed;
    the record then names the class of the exception.
    """
    request = _UNREAD
    try:
        request = _read_request(event)
        rule = _evaluate(request, store, limits, now)
    # decide is the last step before the harness: whatever fails here must deny, not propagate.
    except Exception as error:  # noqa: BLE001
        return _result(request, "R5", type(error).__name__)
    return _result(request, rule)


def undecided(event: object, error: Exception) -> HookResult:
    """Return the R5 denial for an event that could not be decided because of `error`.

    Never raises. For the handler boundary, when no store or limits could be built.
    """
    request = _UNREAD
    # The denial must be returned even if the event cannot be read at all.
    with contextlib.suppress(Exception):
        request = _read_request(event)
    return _result(request, "R5", type(error).__name__)


def _evaluate(
    request: _Request, store: LedgerStore, limits: Limits, now: datetime
) -> RuleId | None:
    """Return the rule that denies the request, or None when it is allowed."""
    if request.call is None:
        return "R5"
    return evaluate(request.call, store.snapshot(now), limits).rule


def _read_request(event: object) -> _Request:
    if not isinstance(event, Mapping):
        return _UNREAD
    return _Request(
        hook_event_id=_text(event.get("hookEventId")),
        session_id=_text(event.get("sessionId")),
        call=_read_call(event),
    )


def _read_call(event: Mapping[object, object]) -> ToolCall | None:
    """Return the tool call of a "before_tool_call" event, or None if any part is unusable."""
    context = event.get("context")
    if event.get("event") != BEFORE_TOOL_CALL or not _is_complete_mapping(context):
        return None
    name, arguments = context.get("toolName"), context.get("toolInput")
    if not isinstance(name, str) or not _is_complete_mapping(arguments):
        return None
    return ToolCall(normalise_tool_name(name), arguments)


def _is_complete_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    """Whether `value` is a mapping the harness did not replace with a truncation marker."""
    # The harness replaces a field that is too large with {"truncated": true, "preview": ...}.
    return isinstance(value, Mapping) and value.get("truncated") is not True


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _result(request: _Request, rule: RuleId | None, error: str | None = None) -> HookResult:
    answer: HookAnswer = (
        {"decision": "allow", "reason": ALLOWED_REASON}
        if rule is None
        else {"decision": "deny", "reason": DENIAL_REASONS[rule]}
    )
    record: HookRecord = {
        "hookEventId": request.hook_event_id,
        "sessionId": request.session_id,
        "tool": None if request.call is None else request.call.name,
        "allowed": rule is None,
        "rule": rule,
        "error": error,
    }
    return HookResult(answer, record)
