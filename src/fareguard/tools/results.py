"""What every tool returns to the agent when it refuses, and how it writes an amount.

A result goes back to the model, so it never repeats text the model sent: a
refusal is a rule id and the fixed sentence of that rule, the same sentence the
hook gives for it.
"""

from decimal import ROUND_DOWN, Decimal
from typing import Literal, TypedDict

from fareguard.gate.models import RuleId
from fareguard.hook.decide import DENIAL_REASONS

_CENT = Decimal("0.01")


class Refusal(TypedDict):
    """A call that was not carried out, and the rule that refused it."""

    refused: Literal[True]
    rule: RuleId
    reason: str


def reason_for(rule: RuleId) -> str:
    """Return the fixed sentence of `rule`. It starts with the rule id."""
    return DENIAL_REASONS[rule]


def refusal(rule: RuleId) -> Refusal:
    """Return the refusal under `rule`."""
    return {"refused": True, "rule": rule, "reason": reason_for(rule)}


def usd(amount: Decimal) -> str:
    """Return `amount` as a string with two decimals, in plain notation.

    Ledger amounts are whole cents already. A cap may hold a fraction of a
    cent; what remains of it is cut, not rounded up, so it is never overstated.
    """
    return format(amount.quantize(_CENT, rounding=ROUND_DOWN), "f")
