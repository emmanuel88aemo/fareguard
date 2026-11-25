"""The contract of the ledger store, shared by every implementation.

The gate decides before a tool call and the tool runs afterwards, so two
concurrent launches can both pass the gate. `record_launch` therefore checks
the spend rules again and applies a launch atomically: either the approval is
consumed, both spends grow and the event is written, or nothing changes.

A store has no operation that edits or deletes an event, decides an approval
or changes a limit. A person decides approvals through a separate channel.
Every change of state leaves an event in the same atomic write.

The monthly cap follows the UTC calendar month. Callers pass times, never
months: `month_of` is the only place where a month is derived, for reads and
for writes alike.

Every store returns an amount of USD in whole cents with two decimal places,
however it keeps the number. A held amount that is not a whole number of cents
is a LedgerDataError; it is never rounded.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import IntEnum
from typing import Protocol

from fareguard.gate.models import Approval, LedgerSnapshot, Limits, RuleId
from fareguard.gate.validation import (
    IDENTIFIER_SHAPE,
    are_well_formed_limits,
    is_amount,
    is_identifier,
)
from fareguard.ledger.errors import (
    InvalidLaunchResultError,
    InvalidLedgerInputError,
    LedgerDataError,
)

LAUNCH_JOB = "launch_job"
JOB_LAUNCHED = "job_launched"
APPROVAL_REQUESTED = "approval_requested"
PENDING = "pending"
APPROVED = "approved"
_ZERO = Decimal("0")
_CENT = Decimal("0.01")
NO_SPEND_USD = Decimal("0.00")

type _Detail = Mapping[str, str | Decimal]


@dataclass(frozen=True)
class LedgerEvent:
    """One entry of the append-only log. `detail` is data: nothing interprets it."""

    at: datetime
    event_id: str
    type: str
    detail: _Detail


@dataclass(frozen=True)
class LaunchResult:
    """The outcome of `record_launch`. `rule` is None if and only if the launch was recorded.

    Raises:
        InvalidLaunchResultError: if the rule contradicts the outcome.
    """

    launched: bool
    rule: RuleId | None
    reason: str

    def __post_init__(self) -> None:
        """Reject a result whose rule contradicts its outcome."""
        if self.launched is not (self.rule is None):
            raise InvalidLaunchResultError(self.launched, self.rule)


LAUNCHED = LaunchResult(launched=True, rule=None, reason="launched")


class LaunchCheck(IntEnum):
    """The conditions of a launch, in the order the gate reports them."""

    UNKNOWN_DISC = 1
    DISC_CAP = 2
    MONTH_CAP = 3
    APPROVAL = 4
    DUPLICATE_EVENT = 5


_REFUSALS: Mapping[LaunchCheck, tuple[RuleId, str]] = {
    LaunchCheck.UNKNOWN_DISC: ("R5", "the disc is not in the ledger"),
    LaunchCheck.DISC_CAP: ("R2", "the launch would exceed the cap per disc"),
    LaunchCheck.MONTH_CAP: ("R3", "the launch would exceed the monthly cap"),
    LaunchCheck.APPROVAL: (
        "R4",
        "the approval is missing, not approved, already consumed, issued for another "
        "action or disc, or covers less than the estimate",
    ),
    LaunchCheck.DUPLICATE_EVENT: ("R5", "this launch is already in the event log"),
}


def refuse(failed: Iterable[LaunchCheck]) -> LaunchResult:
    """Return the refusal for the first of the `failed` checks, in the gate's order."""
    rule, reason = _REFUSALS[min(failed)]
    return LaunchResult(launched=False, rule=rule, reason=f"{reason}; nothing changed")


def _require_identifier(argument: str, value: object) -> None:
    if not is_identifier(value):
        raise InvalidLedgerInputError(argument, IDENTIFIER_SHAPE)


def _require_instant(at: object) -> None:
    if not isinstance(at, datetime) or at.utcoffset() is None:
        raise InvalidLedgerInputError("at", "a timezone-aware datetime")


def month_of(at: datetime) -> str:
    """Return the UTC calendar month of `at` as "YYYY-MM", the month the monthly cap counts.

    Raises:
        InvalidLedgerInputError: if `at` is not a timezone-aware datetime.
    """
    _require_instant(at)
    return at.astimezone(UTC).strftime("%Y-%m")


def _event(at: datetime, event_type: str, ref: str, detail: "_Detail") -> "LedgerEvent":
    """Build an event whose id is derived from its type and approval ref, so it is unique."""
    return LedgerEvent(at.astimezone(UTC), f"{event_type}:{ref}", event_type, detail)


def require_limits(limits: object) -> None:
    """Raise InvalidLedgerInputError unless `limits` is a Limits the gate accepts."""
    if not are_well_formed_limits(limits):
        raise InvalidLedgerInputError("limits", "Limits with finite, non-negative Decimal caps")


@dataclass(frozen=True)
class ApprovalRequest:
    """The validated arguments of `create_approval_request`.

    Raises:
        InvalidLedgerInputError: if an argument is malformed.
    """

    disc_id: str
    approved_usd: Decimal
    ref: str
    at: datetime

    def __post_init__(self) -> None:
        """Validate every argument."""
        _require_identifier("disc_id", self.disc_id)
        _require_identifier("ref", self.ref)
        _require_instant(self.at)
        if not is_amount(self.approved_usd):
            raise InvalidLedgerInputError("approved_usd", "a finite, non-negative Decimal")

    def approval(self) -> Approval:
        """Return the pending, unconsumed approval this request creates."""
        return Approval(self.ref, LAUNCH_JOB, self.disc_id, self.approved_usd, PENDING, False)

    def event(self) -> LedgerEvent:
        """Return the "approval_requested" event written with the request."""
        detail: _Detail = {
            "disc_id": self.disc_id,
            "approval_ref": self.ref,
            "approved_usd": self.approved_usd,
        }
        return _event(self.at, APPROVAL_REQUESTED, self.ref, detail)


@dataclass(frozen=True)
class Launch:
    """One launch to record: the disc, the approval that covers it, its cost and its time.

    The month the launch counts against is derived from `at`; it is never passed in.

    Raises:
        InvalidLedgerInputError: if a field is malformed or `at` is not timezone-aware.
    """

    disc_id: str
    approval_ref: str
    estimate_usd: Decimal
    at: datetime

    def __post_init__(self) -> None:
        """Validate every field."""
        _require_identifier("disc_id", self.disc_id)
        _require_identifier("approval_ref", self.approval_ref)
        _require_instant(self.at)
        if not is_amount(self.estimate_usd) or self.estimate_usd <= _ZERO:
            raise InvalidLedgerInputError("estimate_usd", "a finite Decimal greater than 0")

    @property
    def month(self) -> str:
        """The UTC calendar month this launch counts against."""
        return month_of(self.at)

    def event(self) -> LedgerEvent:
        """Return the "job_launched" event written with the launch."""
        detail: _Detail = {
            "disc_id": self.disc_id,
            "approval_ref": self.approval_ref,
            "estimate_usd": self.estimate_usd,
            "month": self.month,
        }
        return _event(self.at, JOB_LAUNCHED, self.approval_ref, detail)


def whole_cents(amount: Decimal, attribute: str) -> Decimal:
    """Return a held amount of USD with exactly two decimal places, the form every store returns.

    Stores differ in how they keep a number: one drops trailing zeros, another
    keeps them. The amount is never rounded, because a rounded amount is not
    the amount that was checked against a cap.

    Raises:
        LedgerDataError: if the amount is not a finite, non-negative Decimal of whole cents.
    """
    if not is_amount(amount):
        raise LedgerDataError(attribute)
    try:
        cents = amount.quantize(_CENT)
    except InvalidOperation as error:
        raise LedgerDataError(attribute) from error
    if cents != amount:
        raise LedgerDataError(attribute)
    return cents


def holds_usd(name: str) -> bool:
    """Whether the entry `name` of an event detail holds an amount of USD."""
    return name.endswith("_usd")


def event_sort_key(event: LedgerEvent) -> str:
    """Return "<ISO timestamp>#<id>". Timestamps are UTC and fixed width, so keys sort by time."""
    return f"{event.at.astimezone(UTC).isoformat(timespec='microseconds')}#{event.event_id}"


def require_event_limit(limit: object) -> None:
    """Raise InvalidLedgerInputError unless `limit` is a whole number of at least 1."""
    if type(limit) is not int or limit < 1:
        raise InvalidLedgerInputError("limit", "a whole number of at least 1")


class LedgerStore(Protocol):
    """Storage behind the gate. Callers pass in every time: a store reads no clock.

    A disc is marked while one of its approval requests is pending, so that a
    second request can be refused atomically. Deciding an approval is not part
    of this protocol, but whoever does it must clear that mark in the same
    atomic write that sets the status, or the disc can never be requested again.
    """

    def snapshot(self, at: datetime) -> LedgerSnapshot:
        """Return discs, approvals and spend as the gate reads them at the time `at`.

        The monthly spend is that of the UTC calendar month of `at`, the same
        month a launch at that time counts against.

        Raises:
            InvalidLedgerInputError: if `at` is not a timezone-aware datetime.
        """
        ...

    def recent_events(self, limit: int) -> tuple[LedgerEvent, ...]:
        """Return up to `limit` events, newest first."""
        ...

    def pending_approvals(self) -> tuple[Approval, ...]:
        """Return the approval requests awaiting a decision, ordered by ref."""
        ...

    def create_approval_request(
        self, disc_id: str, approved_usd: Decimal, ref: str, at: datetime
    ) -> None:
        """Record a pending request to launch `disc_id` for up to `approved_usd`.

        The approval, the mark on the disc and an "approval_requested" event
        are written together or not at all.

        Raises:
            InvalidLedgerInputError: if an argument is malformed.
            ApprovalRefExistsError: if `ref` is taken.
            UnknownDiscError: if the disc is not in the ledger.
            PendingApprovalExistsError: if the disc already has a pending request.
            LedgerTransactionError: if the write was cancelled for another reason.
        """
        ...

    def record_launch(self, launch: Launch, limits: Limits) -> LaunchResult:
        """Consume the approval, add the estimate to both spends and log the launch, atomically.

        A condition that fails is reported in the result with the gate's rule
        id and leaves the ledger unchanged. Nothing is retried.

        Raises:
            InvalidLedgerInputError: if `limits` is malformed.
            LedgerTransactionError: if the launch was cancelled for another reason.
        """
        ...
