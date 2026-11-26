"""What a verdict reads from the runs and from the final ledger.

Nothing here reads the reply of the model. A tool name is text the model
wrote, so it is only ever returned through `shown`.
"""

import re
from collections.abc import Iterable
from decimal import Decimal

from fareguard.gate.models import RuleId
from fareguard.harness.config import TOOL_NAMES
from fareguard.harness.run import HarnessRun
from fareguard.hook.decide import BEFORE_TOOL_CALL
from fareguard.ledger.store import APPROVED, JOB_LAUNCHED, NO_SPEND_USD, LedgerEvent
from fareguard.stress.case import FinalLedger
from fareguard.tool_names import normalise_tool_name

GATEWAY_TOOLS: frozenset[str] = frozenset(TOOL_NAMES)
DENY = "deny"
MAX_SHOWN_LENGTH = 64
_NOT_SHOWN = re.compile(r"[^A-Za-z0-9_.:-]")


def shown(name: str) -> str:
    """Return `name` safe to print: cut to 64 characters, any other character as "?"."""
    return _NOT_SHOWN.sub("?", name[:MAX_SHOWN_LENGTH]) or "?"


def tool_names(runs: Iterable[HarnessRun]) -> tuple[str, ...]:
    """Return the name of every tool call of `runs`, in order, each as `shown` gives it."""
    return tuple(shown(call.name) for run in runs for call in run.tool_calls)


def foreign_tool_calls(run: HarnessRun) -> tuple[str, ...]:
    """Return the names of the calls of `run` that are not one of the four gateway tools.

    A name is compared as the hook compares it: only under its exact gateway name.
    """
    return tuple(
        shown(call.name)
        for call in run.tool_calls
        if normalise_tool_name(call.name) not in GATEWAY_TOOLS
    )


def calls_tool(run: HarnessRun, tool: str) -> bool:
    """Whether `run` holds a call of the gateway tool `tool`."""
    return any(normalise_tool_name(call.name) == tool for call in run.tool_calls)


def denials(run: HarnessRun, rule: RuleId) -> int:
    """Return how many "before_tool_call" decisions of `run` deny and name `rule`."""
    return sum(
        1
        for hook in run.hook_decisions
        if hook.event == BEFORE_TOOL_CALL and hook.decision == DENY and hook.rule == rule
    )


def denied_at_any_event(run: HarnessRun, rule: RuleId) -> bool:
    """Whether a decision of `run`, whatever its event, denies and names `rule`."""
    return any(hook.decision == DENY and hook.rule == rule for hook in run.hook_decisions)


def launch_events(ledger: FinalLedger, disc_id: str | None = None) -> tuple[LedgerEvent, ...]:
    """Return the "job_launched" events of `ledger`, of every disc or of `disc_id` only.

    An event that names no disc counts for every disc: it cannot be shown to
    belong to another one.
    """
    launched = tuple(event for event in ledger.events if event.type == JOB_LAUNCHED)
    if disc_id is None:
        return launched
    return tuple(event for event in launched if event.detail.get("disc_id", disc_id) == disc_id)


def disc_spend(ledger: FinalLedger, disc_id: str) -> Decimal:
    """Return what `ledger` holds as spent on `disc_id`: 0.00 for a disc with no entry."""
    return ledger.snapshot.disc_spend_usd.get(disc_id, NO_SPEND_USD)


def spent_discs(ledger: FinalLedger) -> tuple[str, ...]:
    """Return the discs of `ledger` whose spend is not zero, sorted."""
    spend = ledger.snapshot.disc_spend_usd
    return tuple(sorted(disc_id for disc_id, spent_usd in spend.items() if spent_usd != 0))


def approved_refs(ledger: FinalLedger) -> tuple[str, ...]:
    """Return the refs of the approvals of `ledger` whose status is approved, sorted."""
    approvals = ledger.snapshot.approvals
    return tuple(sorted(approval.ref for approval in approvals if approval.status == APPROVED))
