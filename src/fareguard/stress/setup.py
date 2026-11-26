"""What the runner does to the ledger around a case, through the store only.

Emptying and seeding the table is the work of scripts/seed.py, which writes
outside the store (decision record 0009). An approval is requested and decided
here exactly as a person would: with `create_approval_request` and
`decide_approval`.
"""

from datetime import datetime
from decimal import Decimal
from typing import Final

from fareguard.gate.models import Limits
from fareguard.ledger.store import LedgerStore
from fareguard.stress.case import ApprovedLaunch, FinalLedger
from fareguard.tools.estimate import estimate_disc

# A case writes a few dozen events at most: twelve iterations per invocation, two invocations.
EVENT_LIMIT: Final = 200


class StressSetupError(Exception):
    """The ledger could not be prepared for a case, or read after it."""


class NoEstimateError(StressSetupError):
    """The disc of an approval is not in the ledger, or its cost cannot be estimated."""

    def __init__(self, disc_id: str) -> None:
        """Name the disc; it comes from the catalogue, not from the agent."""
        super().__init__(f"the cost of {disc_id} cannot be estimated; seed the ledger first")


class TooManyEventsError(StressSetupError):
    """The ledger holds more events than were read, so a launch could be out of sight."""

    def __init__(self) -> None:
        """Say how many events a case may hold."""
        super().__init__(
            f"the ledger holds {EVENT_LIMIT} events or more, so not all were read; "
            "a case starts from an emptied ledger"
        )


def approve_launch(
    store: LedgerStore, launch: ApprovedLaunch, limits: Limits, at: datetime
) -> Decimal:
    """Request and approve the launch of one disc for its estimated cost, and return the cost.

    Raises:
        NoEstimateError: if the disc is unknown or cannot be priced; nothing was written.
        LedgerError: if the store refuses the request or the decision.
    """
    estimate_usd = estimate_disc(store.snapshot(at), launch.disc_id, limits)
    if estimate_usd is None:
        raise NoEstimateError(launch.disc_id)
    store.create_approval_request(launch.disc_id, estimate_usd, launch.ref, at)
    store.decide_approval(launch.ref, True, at)
    return estimate_usd


def read_final_ledger(store: LedgerStore, at: datetime) -> FinalLedger:
    """Return the snapshot of the ledger at `at` with every event it holds.

    Raises:
        TooManyEventsError: if the ledger holds EVENT_LIMIT events or more.
    """
    events = store.recent_events(EVENT_LIMIT)
    if len(events) >= EVENT_LIMIT:
        raise TooManyEventsError
    return FinalLedger(store.snapshot(at), events)
