"""Typed values that cross the boundary of the spend gate."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

type RuleId = Literal["R1", "R2", "R3", "R4"]


@dataclass(frozen=True)
class Limits:
    """Spend limits and the price used to estimate a job."""

    max_usd_per_disc: Decimal = Decimal("1.00")
    monthly_cap_usd: Decimal = Decimal("5.00")
    usd_per_minute: Decimal = Decimal("0.02")


@dataclass(frozen=True)
class Disc:
    """A queued video disc and the duration its cost is computed from."""

    disc_id: str
    duration_seconds: int


@dataclass(frozen=True)
class Approval:
    """A person's answer to a request to run one action on one disc."""

    ref: str
    action: str
    disc_id: str
    approved_usd: Decimal
    status: str
    consumed: bool


@dataclass(frozen=True)
class LedgerSnapshot:
    """The ledger state a decision is based on.

    `disc_spend_usd` maps a disc_id to what was already spent on that disc.
    A disc without an entry has no spend yet.
    """

    discs: tuple[Disc, ...]
    approvals: tuple[Approval, ...]
    month_spend_usd: Decimal
    disc_spend_usd: Mapping[str, Decimal]


@dataclass(frozen=True)
class ToolCall:
    """A tool call proposed by the agent, exactly as it was received."""

    name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True)
class Decision:
    """The outcome of evaluating one tool call.

    `rule` names the rule that denied the call. It is None when the call is
    allowed, and also when the call is denied for malformed input rather than
    for one of the numbered rules.
    """

    allowed: bool
    rule: RuleId | None
    reason: str
