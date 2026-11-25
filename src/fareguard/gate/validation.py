"""Checks that the gate's inputs have the shape and types the rules rely on.

Type annotations are not enforced at run time, so the gate verifies its inputs
before it compares amounts. Every check returns a bool and none raises.
"""

import re
from collections.abc import Iterable, Mapping
from decimal import Decimal

from fareguard.gate.models import Approval, Disc, LedgerSnapshot, Limits, ToolCall

IDENTIFIER_SHAPE = (
    "1 to 64 characters from a-z, 0-9, '.', '_', ':' and '-', starting with a letter or a digit"
)
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._:-]{0,63}")


def is_identifier(value: object) -> bool:
    """Whether `value` is a string with the strict shape of a disc id or an approval ref.

    Only text that passes this check may be quoted in a denial reason, because
    the reason is returned to the agent that supplied the text.
    """
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


def is_amount(value: object) -> bool:
    """Whether `value` is usable as an amount of money: a finite Decimal that is not negative."""
    return isinstance(value, Decimal) and value.is_finite() and value >= Decimal("0")


def _are_unique(values: Iterable[str]) -> bool:
    listed = list(values)
    return len(set(listed)) == len(listed)


def is_well_formed_call(call: object) -> bool:
    """Whether `call` is a ToolCall with a string name and a mapping of arguments."""
    return (
        isinstance(call, ToolCall)
        and isinstance(call.name, str)
        and isinstance(call.arguments, Mapping)
    )


def _is_well_formed_disc(disc: object) -> bool:
    # bool is a subclass of int, so an exact type check keeps True from counting as one second.
    return (
        isinstance(disc, Disc)
        and is_identifier(disc.disc_id)
        and type(disc.duration_seconds) is int
    )


def _is_well_formed_approval(approval: object) -> bool:
    return (
        isinstance(approval, Approval)
        and is_identifier(approval.ref)
        and is_identifier(approval.disc_id)
        and isinstance(approval.action, str)
        and isinstance(approval.status, str)
        and isinstance(approval.consumed, bool)
        and is_amount(approval.approved_usd)
    )


def _has_well_formed_records(snapshot: LedgerSnapshot) -> bool:
    """Whether discs and approvals are typed records with unambiguous identifiers."""
    return (
        isinstance(snapshot.discs, tuple)
        and isinstance(snapshot.approvals, tuple)
        and all(_is_well_formed_disc(disc) for disc in snapshot.discs)
        and all(_is_well_formed_approval(approval) for approval in snapshot.approvals)
        and _are_unique(disc.disc_id for disc in snapshot.discs)
        and _are_unique(approval.ref for approval in snapshot.approvals)
    )


def _has_well_formed_spend(snapshot: LedgerSnapshot) -> bool:
    return (
        is_amount(snapshot.month_spend_usd)
        and isinstance(snapshot.disc_spend_usd, Mapping)
        and all(
            is_identifier(disc_id) and is_amount(spent_usd)
            for disc_id, spent_usd in snapshot.disc_spend_usd.items()
        )
    )


def is_well_formed_snapshot(snapshot: object) -> bool:
    """Whether `snapshot` is a LedgerSnapshot whose records and amounts can be trusted."""
    return (
        isinstance(snapshot, LedgerSnapshot)
        and _has_well_formed_records(snapshot)
        and _has_well_formed_spend(snapshot)
    )


def are_well_formed_limits(limits: object) -> bool:
    """Whether `limits` is a Limits with usable caps and a Decimal rate."""
    return (
        isinstance(limits, Limits)
        and is_amount(limits.max_usd_per_disc)
        and is_amount(limits.monthly_cap_usd)
        and isinstance(limits.usd_per_minute, Decimal)
    )
