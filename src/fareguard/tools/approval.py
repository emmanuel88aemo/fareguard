"""The request_approval tool: ask a person to approve the launch of one disc.

The tool creates a request. It cannot decide one: a person does that through a
channel the agent has no tool for.
"""

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import TypedDict

from fareguard.gate.evaluate import REQUEST_APPROVAL, evaluate
from fareguard.gate.models import Limits, RuleId, ToolCall
from fareguard.ledger.errors import (
    ApprovalRefExistsError,
    InvalidLedgerInputError,
    LedgerError,
    PendingApprovalExistsError,
    UnknownDiscError,
)
from fareguard.ledger.store import LedgerStore
from fareguard.tools.estimate import estimate_disc
from fareguard.tools.results import Detailed, reason_for, usd

REQUESTED_REASON = "requested; a person must decide it before the disc can be launched"
NO_ESTIMATE_DETAIL = "the cost of the disc cannot be estimated"

# What the store refuses, and the rule each refusal is returned under. A ref that is
# already taken is R5: the call could not be carried out, and no rule forbids it.
_STORE_REFUSALS: Mapping[type[LedgerError], RuleId] = {
    PendingApprovalExistsError: "R6",
    ApprovalRefExistsError: "R5",
    UnknownDiscError: "R5",
    InvalidLedgerInputError: "R5",
}


class RequestResult(TypedDict):
    """What request_approval returns.

    `rule` is None if and only if the request was created; `approval_ref` and
    `estimate_usd` are None otherwise. Every refusal names its rule, and
    `reason` is then the fixed sentence of that rule.
    """

    requested: bool
    approval_ref: str | None
    estimate_usd: str | None
    rule: RuleId | None
    reason: str


def request_approval(
    disc_id: str,
    store: LedgerStore,
    limits: Limits,
    now: datetime,
    new_ref: Callable[[], str],
) -> RequestResult:
    """Create a pending request to launch `disc_id` for its estimated cost.

    The estimate comes from the disc's duration in the ledger and the ref from
    `new_ref`; the caller chooses neither. A disc that is unknown, malformed or
    cannot be priced is refused with R5. A refusal by the store is returned as
    a result and changes nothing: R6 for a disc that already has a pending
    request, R5 for a ref that is taken. No reason repeats `disc_id`.
    """
    return request_approval_detailed(disc_id, store, limits, now, new_ref).result


def request_approval_detailed(
    disc_id: str,
    store: LedgerStore,
    limits: Limits,
    now: datetime,
    new_ref: Callable[[], str],
) -> Detailed[RequestResult]:
    """Do what `request_approval` does and also return the detail for the log.

    The detail is the reason of the gate or the message of the store's refusal.
    """
    snapshot = store.snapshot(now)
    decision = evaluate(ToolCall(REQUEST_APPROVAL, {"disc_id": disc_id}), snapshot, limits)
    if decision.rule is not None:
        return _refused(decision.rule, decision.reason)
    estimate_usd = estimate_disc(snapshot, disc_id, limits)
    if estimate_usd is None:
        return _refused("R5", NO_ESTIMATE_DETAIL)
    ref = new_ref()
    try:
        store.create_approval_request(disc_id, estimate_usd, ref, now)
    except tuple(_STORE_REFUSALS) as error:
        return _refused(_STORE_REFUSALS[type(error)], str(error))
    result: RequestResult = {
        "requested": True,
        "approval_ref": ref,
        "estimate_usd": usd(estimate_usd),
        "rule": None,
        "reason": REQUESTED_REASON,
    }
    return Detailed(result, decision.reason)


def _refused(rule: RuleId, detail: str) -> Detailed[RequestResult]:
    result: RequestResult = {
        "requested": False,
        "approval_ref": None,
        "estimate_usd": None,
        "rule": rule,
        "reason": reason_for(rule),
    }
    return Detailed(result, detail)
