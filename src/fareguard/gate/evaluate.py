"""Allow or deny one proposed tool call against the rules R1 to R5."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from fareguard.gate.models import (
    Approval,
    Decision,
    Disc,
    LedgerSnapshot,
    Limits,
    RuleId,
    ToolCall,
)
from fareguard.gate.pricing import PricingError, estimate_cost
from fareguard.gate.validation import (
    are_well_formed_limits,
    is_well_formed_call,
    is_well_formed_snapshot,
)

READ_LEDGER = "read_ledger"
LIST_PENDING = "list_pending"
REQUEST_APPROVAL = "request_approval"
LAUNCH_JOB = "launch_job"

_READ_TOOLS: frozenset[str] = frozenset({READ_LEDGER, LIST_PENDING})
_TOOLS: frozenset[str] = _READ_TOOLS | {REQUEST_APPROVAL, LAUNCH_JOB}
_REQUEST_APPROVAL_ARGUMENTS: frozenset[str] = frozenset({"disc_id"})
_LAUNCH_JOB_ARGUMENTS: frozenset[str] = frozenset({"disc_id", "approval_ref"})
_APPROVED = "approved"
_ZERO = Decimal("0")
_ALLOWED = Decision(allowed=True, rule=None, reason="allowed")


@dataclass(frozen=True)
class _Launch:
    """A launch_job call whose arguments were validated and whose cost was estimated."""

    disc_id: str
    approval_ref: str
    estimate_usd: Decimal


def evaluate(call: ToolCall, snapshot: LedgerSnapshot, limits: Limits) -> Decision:
    """Decide whether `call` may run, given the ledger `snapshot` and `limits`.

    Never raises: a call that is malformed or cannot be evaluated, because of
    its own shape or that of the snapshot or the limits, is denied with R5.
    Every denial names the rule that failed. The cost of a job is always
    computed from the disc's duration in the snapshot, never taken from the call.
    """
    if not is_well_formed_call(call):
        return _deny("R5", "the tool call must have a string name and a mapping of arguments")
    if call.name not in _TOOLS:
        tools = ", ".join(sorted(_TOOLS))
        return _deny("R1", f"tool {call.name!r} does not exist; the only tools are {tools}")
    return _evaluate_known_tool(call, snapshot, limits)


def _evaluate_known_tool(call: ToolCall, snapshot: LedgerSnapshot, limits: Limits) -> Decision:
    if call.name in _READ_TOOLS:
        return _evaluate_read(call)
    if not is_well_formed_snapshot(snapshot):
        return _deny("R5", "the ledger snapshot is malformed, so no spend can be checked")
    if call.name == REQUEST_APPROVAL:
        return _evaluate_request_approval(call, snapshot)
    return _evaluate_launch_job(call, snapshot, limits)


def _evaluate_read(call: ToolCall) -> Decision:
    if len(call.arguments) > 0:
        return _deny("R5", f"{call.name} takes no arguments; got {_describe(call.arguments)}")
    return _ALLOWED


def _evaluate_request_approval(call: ToolCall, snapshot: LedgerSnapshot) -> Decision:
    arguments = _string_arguments(call.arguments, _REQUEST_APPROVAL_ARGUMENTS)
    if arguments is None:
        return _deny_arguments(call, _REQUEST_APPROVAL_ARGUMENTS)
    if _find_disc(snapshot, arguments["disc_id"]) is None:
        return _deny_unknown_disc(arguments["disc_id"])
    return _ALLOWED


def _evaluate_launch_job(call: ToolCall, snapshot: LedgerSnapshot, limits: Limits) -> Decision:
    arguments = _string_arguments(call.arguments, _LAUNCH_JOB_ARGUMENTS)
    if arguments is None:
        return _deny_arguments(call, _LAUNCH_JOB_ARGUMENTS)
    if not are_well_formed_limits(limits):
        return _deny("R5", "the limits are malformed, so no spend can be checked")
    disc = _find_disc(snapshot, arguments["disc_id"])
    if disc is None:
        return _deny_unknown_disc(arguments["disc_id"])
    return _evaluate_launch(disc, arguments["approval_ref"], snapshot, limits)


def _evaluate_launch(
    disc: Disc, approval_ref: str, snapshot: LedgerSnapshot, limits: Limits
) -> Decision:
    try:
        estimate_usd = estimate_cost(disc.duration_seconds, limits.usd_per_minute)
    except PricingError as error:
        return _deny("R5", f"the cost of disc {disc.disc_id!r} cannot be estimated: {error}")
    launch = _Launch(disc.disc_id, approval_ref, estimate_usd)
    return (
        _check_disc_cap(launch, snapshot, limits)
        or _check_monthly_cap(launch, snapshot, limits)
        or _check_approval(launch, snapshot)
        or _ALLOWED
    )


def _check_disc_cap(launch: _Launch, snapshot: LedgerSnapshot, limits: Limits) -> Decision | None:
    """R2: what was spent on the disc plus the estimate stays within the per-disc cap."""
    spent_usd = snapshot.disc_spend_usd.get(launch.disc_id, _ZERO)
    total_usd = spent_usd + launch.estimate_usd
    if total_usd <= limits.max_usd_per_disc:
        return None
    return _deny(
        "R2",
        f"disc {launch.disc_id!r}: {spent_usd} USD already spent plus the "
        f"{launch.estimate_usd} USD estimate is {total_usd} USD, over the cap of "
        f"{limits.max_usd_per_disc} USD per disc",
    )


def _check_monthly_cap(
    launch: _Launch, snapshot: LedgerSnapshot, limits: Limits
) -> Decision | None:
    """R3: what was spent this month plus the estimate stays within the monthly cap."""
    total_usd = snapshot.month_spend_usd + launch.estimate_usd
    if total_usd <= limits.monthly_cap_usd:
        return None
    return _deny(
        "R3",
        f"{snapshot.month_spend_usd} USD already spent this month plus the "
        f"{launch.estimate_usd} USD estimate is {total_usd} USD, over the monthly cap of "
        f"{limits.monthly_cap_usd} USD",
    )


def _check_approval(launch: _Launch, snapshot: LedgerSnapshot) -> Decision | None:
    """R4: an unused approval for this action, this disc and at least this amount exists."""
    approval = next((a for a in snapshot.approvals if a.ref == launch.approval_ref), None)
    if approval is None:
        return _deny("R4", f"no approval with ref {launch.approval_ref!r} exists")
    problem = _approval_problem(approval, launch)
    if problem is None:
        return None
    return _deny("R4", f"approval {approval.ref!r} {problem}")


def _approval_problem(approval: Approval, launch: _Launch) -> str | None:
    """Return why `approval` does not cover `launch`, or None when it does."""
    checks = (
        (approval.status != _APPROVED, f"has status {approval.status!r}, not {_APPROVED!r}"),
        (approval.consumed, "has already been consumed"),
        (
            approval.action != LAUNCH_JOB,
            f"was issued for the action {approval.action!r}, not {LAUNCH_JOB!r}",
        ),
        (
            approval.disc_id != launch.disc_id,
            f"was issued for disc {approval.disc_id!r}, not {launch.disc_id!r}",
        ),
        (
            approval.approved_usd < launch.estimate_usd,
            f"covers {approval.approved_usd} USD, less than the {launch.estimate_usd} USD estimate",
        ),
    )
    return next((reason for failed, reason in checks if failed), None)


def _string_arguments(
    arguments: Mapping[str, object], expected: frozenset[str]
) -> dict[str, str] | None:
    """Return the arguments when they are exactly the `expected` keys with string values."""
    if set(arguments) != expected:
        return None
    strings = {key: value for key, value in arguments.items() if isinstance(value, str)}
    return strings if len(strings) == len(expected) else None


def _find_disc(snapshot: LedgerSnapshot, disc_id: str) -> Disc | None:
    return next((disc for disc in snapshot.discs if disc.disc_id == disc_id), None)


def _deny(rule: RuleId, reason: str) -> Decision:
    return Decision(allowed=False, rule=rule, reason=reason)


def _deny_arguments(call: ToolCall, expected: frozenset[str]) -> Decision:
    names = ", ".join(sorted(expected))
    return _deny(
        "R5",
        f"{call.name} takes exactly the string arguments {names}; got {_describe(call.arguments)}",
    )


def _deny_unknown_disc(disc_id: str) -> Decision:
    return _deny("R5", f"disc {disc_id!r} is not in the ledger snapshot")


def _describe(arguments: Mapping[str, object]) -> str:
    """List argument names and value types, without echoing the values."""
    if len(arguments) == 0:
        return "no arguments"
    return ", ".join(
        sorted(f"{key!r} ({type(value).__name__})" for key, value in arguments.items())
    )
