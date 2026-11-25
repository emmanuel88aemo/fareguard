"""The named errors of the ledger.

Messages never repeat a malformed value, because it may come from the model.
An identifier is quoted only after it passed the gate's shape check.
"""

from collections.abc import Iterable

from fareguard.gate.models import RuleId


class LedgerError(Exception):
    """Base class of every error raised by a ledger store."""


class InvalidLedgerInputError(LedgerError, ValueError):
    """An argument does not have the shape the ledger accepts."""

    def __init__(self, argument: str, expected: str) -> None:
        """Name the argument without repeating its value, which may come from the model."""
        super().__init__(f"{argument} is malformed; expected {expected}")


class ApprovalRefExistsError(LedgerError):
    """An approval with this ref already exists."""

    def __init__(self, ref: str) -> None:
        """Record the ref that is taken."""
        super().__init__(f"an approval with ref {ref!r} already exists")


class PendingApprovalExistsError(LedgerError):
    """The disc already has an approval request awaiting a decision."""

    def __init__(self, disc_id: str) -> None:
        """Record the disc that already has a pending request."""
        super().__init__(f"disc {disc_id!r} already has a pending approval request")


class UnknownDiscError(LedgerError):
    """The disc is not in the ledger."""

    def __init__(self, disc_id: str) -> None:
        """Record the disc that was not found."""
        super().__init__(f"disc {disc_id!r} is not in the ledger")


class LedgerTransactionError(LedgerError):
    """A transaction was cancelled for a reason other than a failed condition."""

    def __init__(self, codes: Iterable[str]) -> None:
        """Record the cancellation codes reported by the store."""
        super().__init__(f"the transaction was cancelled and nothing changed: {', '.join(codes)}")


class InvalidLaunchResultError(ValueError):
    """A LaunchResult was built with a rule that contradicts its outcome."""

    def __init__(self, launched: bool, rule: RuleId | None) -> None:
        """Record the contradicting pair."""
        super().__init__(
            "a launch result names a rule if and only if the launch was refused; "
            f"got launched={launched!r} with rule={rule!r}"
        )
