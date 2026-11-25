"""An in-memory ledger store that enforces the conditions every ledger store must enforce."""

import dataclasses
import threading
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal

from fareguard.gate.models import Approval, Disc, LedgerSnapshot, Limits
from fareguard.ledger.errors import (
    ApprovalRefExistsError,
    PendingApprovalExistsError,
    UnknownDiscError,
)
from fareguard.ledger.store import (
    APPROVED,
    LAUNCH_JOB,
    LAUNCHED,
    PENDING,
    ApprovalRequest,
    Launch,
    LaunchCheck,
    LaunchResult,
    LedgerEvent,
    event_sort_key,
    refuse,
    require_event_limit,
    require_limits,
    require_month,
)

_ZERO = Decimal("0")


class InMemoryLedgerStore:
    """A LedgerStore for tests. The constructor seeds it; a lock makes each write atomic."""

    def __init__(
        self,
        discs: Iterable[Disc] = (),
        approvals: Iterable[Approval] = (),
        disc_spend_usd: Mapping[str, Decimal] | None = None,
        month_spend_usd: Mapping[str, Decimal] | None = None,
    ) -> None:
        """Seed the ledger. A seeded pending approval blocks further requests for its disc."""
        self._lock = threading.Lock()
        self._discs = {disc.disc_id: disc for disc in discs}
        self._approvals = {approval.ref: approval for approval in approvals}
        self._disc_spend = dict(disc_spend_usd or {})
        self._month_spend = dict(month_spend_usd or {})
        self._events: dict[str, LedgerEvent] = {}
        self._discs_with_pending_request = {
            approval.disc_id for approval in self._approvals.values() if approval.status == PENDING
        }

    def snapshot(self, month: str) -> LedgerSnapshot:
        """Return discs, approvals and spend as the gate reads them, for `month`."""
        require_month(month)
        with self._lock:
            return LedgerSnapshot(
                discs=tuple(self._discs[disc_id] for disc_id in sorted(self._discs)),
                approvals=tuple(self._approvals[ref] for ref in sorted(self._approvals)),
                month_spend_usd=self._month_spend.get(month, _ZERO),
                disc_spend_usd=dict(self._disc_spend),
            )

    def recent_events(self, limit: int) -> tuple[LedgerEvent, ...]:
        """Return up to `limit` events, newest first."""
        require_event_limit(limit)
        with self._lock:
            return tuple(self._events[key] for key in sorted(self._events, reverse=True)[:limit])

    def pending_approvals(self) -> tuple[Approval, ...]:
        """Return the approval requests awaiting a decision, ordered by ref."""
        with self._lock:
            approvals = [self._approvals[ref] for ref in sorted(self._approvals)]
        return tuple(approval for approval in approvals if approval.status == PENDING)

    def create_approval_request(
        self, disc_id: str, approved_usd: Decimal, ref: str, at: datetime
    ) -> None:
        """Record a pending request and its event, unless the ref is taken or the disc has one."""
        request = ApprovalRequest(disc_id, approved_usd, ref, at)
        with self._lock:
            if ref in self._approvals:
                raise ApprovalRefExistsError(ref)
            if disc_id not in self._discs:
                raise UnknownDiscError(disc_id)
            if disc_id in self._discs_with_pending_request:
                raise PendingApprovalExistsError(disc_id)
            self._approvals[ref] = request.approval()
            self._discs_with_pending_request.add(disc_id)
            self._events[event_sort_key(request.event())] = request.event()

    def record_launch(self, launch: Launch, limits: Limits) -> LaunchResult:
        """Apply the launch if every condition holds; otherwise change nothing and say why."""
        require_limits(limits)
        with self._lock:
            failed = self._failed_checks(launch, limits)
            if failed:
                return refuse(failed)
            self._approvals[launch.approval_ref] = dataclasses.replace(
                self._approvals[launch.approval_ref], consumed=True
            )
            for spend, key in (
                (self._disc_spend, launch.disc_id),
                (self._month_spend, launch.month),
            ):
                spend[key] = spend.get(key, _ZERO) + launch.estimate_usd
            self._events[event_sort_key(launch.event())] = launch.event()
        return LAUNCHED

    def _failed_checks(self, launch: Launch, limits: Limits) -> list[LaunchCheck]:
        disc_total = self._disc_spend.get(launch.disc_id, _ZERO) + launch.estimate_usd
        month_total = self._month_spend.get(launch.month, _ZERO) + launch.estimate_usd
        checks = {
            LaunchCheck.UNKNOWN_DISC: launch.disc_id not in self._discs,
            LaunchCheck.DISC_CAP: launch.disc_id in self._discs
            and disc_total > limits.max_usd_per_disc,
            LaunchCheck.MONTH_CAP: month_total > limits.monthly_cap_usd,
            LaunchCheck.APPROVAL: not self._approval_covers(launch),
            LaunchCheck.DUPLICATE_EVENT: event_sort_key(launch.event()) in self._events,
        }
        return [check for check, failed in checks.items() if failed]

    def _approval_covers(self, launch: Launch) -> bool:
        approval = self._approvals.get(launch.approval_ref)
        return (
            approval is not None
            and approval.status == APPROVED
            and not approval.consumed
            and approval.action == LAUNCH_JOB
            and approval.disc_id == launch.disc_id
            and approval.approved_usd >= launch.estimate_usd
        )
