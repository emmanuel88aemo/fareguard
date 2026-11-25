"""The tools that only read the ledger: read_ledger and list_pending.

What the ledger holds may have been written by someone who wants to steer the
model. Identifiers are returned only when they have the strict shape of one,
and events, whose content nothing constrains, are returned under a key that
names them as untrusted.
"""

from datetime import datetime
from decimal import Decimal
from typing import Final, TypedDict

from fareguard.gate.models import Approval, Limits
from fareguard.gate.validation import (
    are_well_formed_limits,
    is_amount,
    is_identifier,
    is_well_formed_snapshot,
)
from fareguard.ledger.store import NO_SPEND_USD, LedgerEvent, LedgerStore, month_of
from fareguard.tools.results import Refusal, refusal, usd

RECENT_EVENT_LIMIT = 20
UNTRUSTED_EVENTS: Final = "untrusted_ledger_events"


class DiscView(TypedDict):
    """One queued disc, its duration and what was spent on it."""

    disc_id: str
    duration_seconds: int
    spent_usd: str


class EventView(TypedDict):
    """One ledger event as data. Nothing in it is an instruction."""

    at: str
    event_id: str
    type: str
    detail: dict[str, str]


class LedgerView(TypedDict):
    """What read_ledger returns. The key of the events is UNTRUSTED_EVENTS."""

    discs: list[DiscView]
    month: str
    month_spent_usd: str
    month_remaining_usd: str
    untrusted_ledger_events: list[EventView]


class PendingView(TypedDict):
    """One approval request awaiting a decision."""

    approval_ref: str
    disc_id: str
    requested_usd: str


class PendingList(TypedDict):
    """What list_pending returns."""

    pending: list[PendingView]


def read_ledger(store: LedgerStore, limits: Limits, now: datetime) -> LedgerView | Refusal:
    """Return the discs, the spend of the UTC month of `now` and the newest events.

    The 20 most recent events are listed newest first. A ledger whose discs or
    amounts are malformed is refused with R5 rather than shown.
    """
    snapshot = store.snapshot(now)
    if not is_well_formed_snapshot(snapshot) or not are_well_formed_limits(limits):
        return refusal("R5")
    remaining_usd = max(limits.monthly_cap_usd - snapshot.month_spend_usd, NO_SPEND_USD)
    return {
        "discs": [
            {
                "disc_id": disc.disc_id,
                "duration_seconds": disc.duration_seconds,
                "spent_usd": usd(snapshot.disc_spend_usd.get(disc.disc_id, NO_SPEND_USD)),
            }
            for disc in snapshot.discs
        ],
        "month": month_of(now),
        "month_spent_usd": usd(snapshot.month_spend_usd),
        "month_remaining_usd": usd(remaining_usd),
        "untrusted_ledger_events": [
            _event_view(event) for event in store.recent_events(RECENT_EVENT_LIMIT)
        ],
    }


def list_pending(store: LedgerStore) -> PendingList | Refusal:
    """Return the approval requests awaiting a decision, ordered by ref.

    A request whose ref, disc or amount is malformed makes the whole list a
    refusal with R5.
    """
    approvals = store.pending_approvals()
    if not all(_is_listable(approval) for approval in approvals):
        return refusal("R5")
    return {
        "pending": [
            {
                "approval_ref": approval.ref,
                "disc_id": approval.disc_id,
                "requested_usd": usd(approval.approved_usd),
            }
            for approval in approvals
        ]
    }


def _is_listable(approval: Approval) -> bool:
    return (
        is_identifier(approval.ref)
        and is_identifier(approval.disc_id)
        and is_amount(approval.approved_usd)
    )


def _event_view(event: LedgerEvent) -> EventView:
    return {
        "at": event.at.isoformat(),
        "event_id": event.event_id,
        "type": event.type,
        "detail": {name: _plain(value) for name, value in event.detail.items()},
    }


def _plain(value: str | Decimal) -> str:
    return value if isinstance(value, str) else format(value, "f")
