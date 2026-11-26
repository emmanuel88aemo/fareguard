"""Answer a "before_tool_call" event of the harness with allow or deny.

The harness invokes the hook before every tool call. The model cannot call it
or influence it, and the reason it returns goes back to the model. A reason is
therefore a fixed sentence chosen by the rule that denied: it never repeats
text from the event. What the model no longer sees is kept in the log record:
the gate's own reason and the tool name as it arrived.
"""

import contextlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypedDict, TypeGuard

from fareguard.gate.evaluate import evaluate
from fareguard.gate.models import Limits, RuleId, ToolCall
from fareguard.ledger.store import LedgerStore
from fareguard.tool_names import normalise_tool_name

BEFORE_TOOL_CALL = "before_tool_call"
MAX_REASON_LENGTH = 1024
MAX_RAW_TOOL_LENGTH = 128

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
    "R6": "R6: the disc already has an approval request awaiting a decision",
    "R7": "R7: the content guardrail blocked the text of this event",
}


class HookAnswer(TypedDict):
    """What the harness expects back from the hook."""

    decision: Literal["allow", "deny"]
    reason: str


class HookRecord(TypedDict):
    """One decision as it is logged. It is never returned to the harness.

    `detail` is the gate's own reason, or None when the gate was not reached.
    It may quote a disc id or an approval ref of the call, but only one with
    the strict shape of an identifier; no other argument text is recorded.
    `raw_tool` is the tool name exactly as it arrived, cut to
    MAX_RAW_TOOL_LENGTH characters. `error` is the class name of an exception
    that forced the denial, or None.
    """

    # The identifiers keep the spelling the harness uses, so a log line matches its event.
    hookEventId: str | None
    sessionId: str | None
    tool: str | None
    raw_tool: str | None
    allowed: bool
    rule: RuleId | None
    detail: str | None
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
    raw_tool: str | None = None
    call: ToolCall | None = None


@dataclass(frozen=True)
class _Outcome:
    """The rule that denies, or None, with the gate's reason when the gate was reached."""

    rule: RuleId | None
    detail: str | None = None


_UNREAD = _Request()
_UNEVALUATED = _Outcome("R5")


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
        decision = _evaluate(request, store, limits, now)
    # decide is the last step before the harness: whatever fails here must deny, not propagate.
    except Exception as error:  # noqa: BLE001
        return _result(request, _UNEVALUATED, type(error).__name__)
    return _result(request, decision)


def undecided(event: object, error: Exception) -> HookResult:
    """Return the R5 denial for an event that could not be decided because of `error`.

    Never raises. For the handler boundary, when no store or limits could be built.
    """
    request = _UNREAD
    # The denial must be returned even if the event cannot be read at all.
    with contextlib.suppress(Exception):
        request = _read_request(event)
    return _result(request, _UNEVALUATED, type(error).__name__)


def _evaluate(request: _Request, store: LedgerStore, limits: Limits, now: datetime) -> _Outcome:
    """Return the gate's outcome for the request, or the R5 denial of an unusable event."""
    if request.call is None:
        return _UNEVALUATED
    decision = evaluate(request.call, store.snapshot(now), limits)
    return _Outcome(decision.rule, decision.reason)


def _read_request(event: object) -> _Request:
    if not isinstance(event, Mapping):
        return _UNREAD
    return _Request(
        hook_event_id=_text(event.get("hookEventId")),
        session_id=_text(event.get("sessionId")),
        raw_tool=_read_raw_tool(event),
        call=_read_call(event),
    )


def _read_raw_tool(event: Mapping[object, object]) -> str | None:
    """Return the tool name as it arrived, cut short, whatever else is wrong with the event."""
    context = event.get("context")
    name = context.get("toolName") if isinstance(context, Mapping) else None
    return name[:MAX_RAW_TOOL_LENGTH] if isinstance(name, str) else None


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


def _result(request: _Request, outcome: _Outcome, error: str | None = None) -> HookResult:
    rule = outcome.rule
    answer: HookAnswer = (
        {"decision": "allow", "reason": ALLOWED_REASON}
        if rule is None
        else {"decision": "deny", "reason": DENIAL_REASONS[rule]}
    )
    record: HookRecord = {
        "hookEventId": request.hook_event_id,
        "sessionId": request.session_id,
        "tool": None if request.call is None else request.call.name,
        "raw_tool": request.raw_tool,
        "allowed": rule is None,
        "rule": rule,
        "detail": outcome.detail,
        "error": error,
    }
    return HookResult(answer, record)
