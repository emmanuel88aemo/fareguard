"""Route one tool call to the tool that carries it out."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from fareguard.gate.evaluate import LAUNCH_JOB, LIST_PENDING, READ_LEDGER, REQUEST_APPROVAL
from fareguard.gate.models import Limits
from fareguard.gate.validation import is_identifier
from fareguard.ledger.store import LedgerStore
from fareguard.tools.approval import RequestResult, request_approval_detailed
from fareguard.tools.launch import LaunchOutcome, launch_job_detailed
from fareguard.tools.read import LedgerView, PendingList, list_pending, read_ledger
from fareguard.tools.results import Detailed, Refusal, refusal

type ToolResult = LedgerView | PendingList | RequestResult | LaunchOutcome | Refusal

NO_CALL_DETAIL = "the tool name is not a string or the arguments are not a mapping"
UNKNOWN_TOOL_DETAIL = "the requested tool does not exist"
ARGUMENTS_DETAIL = (
    "the arguments are not exactly those of the tool, each a string with the shape of an identifier"
)

# The arguments each tool takes. Every one is a string with the shape of an identifier.
_ARGUMENTS: Mapping[str, tuple[str, ...]] = {
    READ_LEDGER: (),
    LIST_PENDING: (),
    REQUEST_APPROVAL: ("disc_id",),
    LAUNCH_JOB: ("disc_id", "approval_ref"),
}


@dataclass(frozen=True)
class ToolContext:
    """What the tools work with: the ledger, the limits, the time and a source of refs."""

    store: LedgerStore
    limits: Limits
    now: datetime
    new_ref: Callable[[], str]


def dispatch(tool_name: object, arguments: object, context: ToolContext) -> Detailed[ToolResult]:
    """Carry out the call of `tool_name` with `arguments`, or refuse it.

    `tool_name` is the plain name, without a gateway target. A name that is
    not one of the four tools is refused with R1. A missing name and arguments
    that are not exactly the tool's own, each a string with the shape of an
    identifier, are refused with R5. A refusal repeats nothing from the call.

    The result is for the agent. The detail beside it is for the log only.
    """
    if not isinstance(tool_name, str) or not isinstance(arguments, Mapping):
        return Detailed(refusal("R5"), NO_CALL_DETAIL)
    expected = _ARGUMENTS.get(tool_name)
    if expected is None:
        return Detailed(refusal("R1"), UNKNOWN_TOOL_DETAIL)
    if set(arguments) != set(expected) or not all(is_identifier(arguments[n]) for n in expected):
        return Detailed(refusal("R5"), ARGUMENTS_DETAIL)
    return _run(tool_name, arguments, context)


def _run(
    tool_name: str, arguments: Mapping[str, str], context: ToolContext
) -> Detailed[ToolResult]:
    store, limits, now = context.store, context.limits, context.now
    if tool_name == READ_LEDGER:
        return Detailed(read_ledger(store, limits, now), None)
    if tool_name == LIST_PENDING:
        return Detailed(list_pending(store), None)
    if tool_name == REQUEST_APPROVAL:
        return request_approval_detailed(arguments["disc_id"], store, limits, now, context.new_ref)
    return launch_job_detailed(arguments["disc_id"], arguments["approval_ref"], store, limits, now)
