"""The launch_job tool: record the launch of one disc under an approval."""

from datetime import datetime
from typing import TypedDict

from fareguard.gate.evaluate import LAUNCH_JOB, evaluate
from fareguard.gate.models import Limits, RuleId, ToolCall
from fareguard.ledger.store import Launch, LedgerStore
from fareguard.tools.estimate import estimate_disc
from fareguard.tools.results import Detailed, reason_for

LAUNCHED_REASON = "launched"
NO_ESTIMATE_DETAIL = "the cost of the disc cannot be estimated"


class LaunchOutcome(TypedDict):
    """What launch_job returns. `rule` is None if and only if the job was launched."""

    launched: bool
    rule: RuleId | None
    reason: str


def launch_job(
    disc_id: str,
    approval_ref: str,
    store: LedgerStore,
    limits: Limits,
    now: datetime,
) -> LaunchOutcome:
    """Launch the job of `disc_id` under `approval_ref`, if every rule allows it.

    The launch is simulated: nothing is started outside the ledger. The ledger
    record written by `store.record_launch` is the job.

    The tool does not assume the hook ran. It takes its own snapshot and asks
    the gate again; only when the gate allows does it call the store, which
    checks the rules once more inside its atomic write. A refusal from either
    names its rule and changes nothing. The reason in the result is the fixed
    sentence of that rule: it repeats neither argument.
    """
    return launch_job_detailed(disc_id, approval_ref, store, limits, now).result


def launch_job_detailed(
    disc_id: str,
    approval_ref: str,
    store: LedgerStore,
    limits: Limits,
    now: datetime,
) -> Detailed[LaunchOutcome]:
    """Do what `launch_job` does and also return the detail for the log.

    The detail is the reason of the gate or of the store, whichever answered last.
    """
    snapshot = store.snapshot(now)
    call = ToolCall(LAUNCH_JOB, {"disc_id": disc_id, "approval_ref": approval_ref})
    decision = evaluate(call, snapshot, limits)
    estimate_usd = estimate_disc(snapshot, disc_id, limits)
    if decision.rule is not None:
        return _refused(decision.rule, decision.reason)
    if estimate_usd is None:
        return _refused("R5", NO_ESTIMATE_DETAIL)
    result = store.record_launch(Launch(disc_id, approval_ref, estimate_usd, now), limits)
    if result.rule is not None:
        return _refused(result.rule, result.reason)
    return Detailed({"launched": True, "rule": None, "reason": LAUNCHED_REASON}, result.reason)


def _refused(rule: RuleId, detail: str) -> Detailed[LaunchOutcome]:
    return Detailed({"launched": False, "rule": rule, "reason": reason_for(rule)}, detail)
