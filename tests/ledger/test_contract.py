"""The contract every LedgerStore must honour. It runs once per implementation."""

import dataclasses
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from fareguard.gate.evaluate import evaluate
from fareguard.gate.models import Approval, Disc, LedgerSnapshot, Limits, ToolCall
from fareguard.gate.pricing import estimate_cost
from fareguard.gate.validation import is_well_formed_snapshot
from fareguard.ledger.errors import (
    ApprovalDiscMismatchError,
    ApprovalNotPendingError,
    ApprovalRefExistsError,
    InvalidLedgerInputError,
    LedgerDataError,
    LedgerError,
    LedgerTransactionError,
    PendingApprovalExistsError,
    UnknownApprovalError,
    UnknownDiscError,
)
from fareguard.ledger.store import DecidedApproval, Launch, LedgerEvent, LedgerStore, month_of

type MakeStore = Callable[..., LedgerStore]
type State = tuple[LedgerSnapshot, tuple[LedgerEvent, ...]]
# A decision that loses a race is refused by its condition or cancelled as a conflict.
type DecisionOutcome = DecidedApproval | LedgerError

AT = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)
MONTH = month_of(AT)
LIMITS = Limits()
ESTIMATE = Decimal("0.20")
# Ten minutes at the default rate: an estimate of 0.20 USD.
DISC = Disc("disc-1", 600)
OTHER_DISC = Disc("disc-2", 600)
DISCS = (DISC, OTHER_DISC)
APPROVAL = Approval("apr-1", "launch_job", "disc-1", ESTIMATE, "approved", False)
LAUNCH = Launch("disc-1", "apr-1", ESTIMATE, AT)
PENDING = dataclasses.replace(APPROVAL, status="pending")
DECIDED_AT = AT + timedelta(minutes=1)
LAUNCH_AFTER_DECISION = Launch("disc-1", "apr-1", ESTIMATE, AT + timedelta(minutes=2))
BARRIER_TIMEOUT_SECONDS = 30
RACE_ROUNDS = 5


def approval(**changes: object) -> Approval:
    return dataclasses.replace(APPROVAL, **changes)  # type: ignore[arg-type]  # test helper takes any field


def state(store: LedgerStore) -> State:
    """Everything observable through the store: the snapshot and the whole event log."""
    return store.snapshot(AT), store.recent_events(100)


def test_recorded_launch_changes_all_four_items(make_store: MakeStore) -> None:
    store = make_store(DISCS, [APPROVAL])

    result = store.record_launch(LAUNCH, LIMITS)

    snapshot, events = state(store)
    assert result.launched is True
    assert result.rule is None
    assert snapshot.approvals == (approval(consumed=True),)
    assert snapshot.disc_spend_usd == {"disc-1": ESTIMATE}
    assert snapshot.month_spend_usd == ESTIMATE
    assert events == (LAUNCH.event(),)


@dataclasses.dataclass(frozen=True)
class Seed:
    """What a store holds before the launch under test."""

    approvals: tuple[Approval, ...] = (APPROVAL,)
    disc_spend: Mapping[str, Decimal] = dataclasses.field(default_factory=dict)
    month_spend: Mapping[str, Decimal] = dataclasses.field(default_factory=dict)


@pytest.mark.parametrize(
    ("seed", "launch", "rule"),
    [
        pytest.param(Seed(approvals=()), LAUNCH, "R4", id="no-approval"),
        pytest.param(
            Seed(approvals=(approval(consumed=True),)),
            LAUNCH,
            "R4",
            id="A5-approval-already-consumed",
        ),
        pytest.param(
            Seed(approvals=(approval(status="pending"),)), LAUNCH, "R4", id="approval-pending"
        ),
        pytest.param(
            Seed(approvals=(approval(status="rejected"),)), LAUNCH, "R4", id="approval-rejected"
        ),
        pytest.param(
            Seed(approvals=(approval(action="request_approval"),)),
            LAUNCH,
            "R4",
            id="approval-other-action",
        ),
        pytest.param(
            Seed(approvals=(approval(disc_id="disc-2"),)), LAUNCH, "R4", id="approval-other-disc"
        ),
        pytest.param(
            Seed(approvals=(approval(approved_usd=Decimal("0.19")),)),
            LAUNCH,
            "R4",
            id="approval-too-small",
        ),
        pytest.param(
            Seed(disc_spend={"disc-1": Decimal("0.81")}), LAUNCH, "R2", id="disc-cap-by-one-cent"
        ),
        pytest.param(
            Seed(approvals=(approval(approved_usd=Decimal("1.50")),)),
            Launch("disc-1", "apr-1", Decimal("1.50"), AT),
            "R2",
            id="A3-estimate-alone-over-the-disc-cap",
        ),
        pytest.param(
            Seed(month_spend={MONTH: Decimal("4.81")}), LAUNCH, "R3", id="month-cap-by-one-cent"
        ),
        pytest.param(
            Seed(approvals=(approval(disc_id="disc-9"),)),
            Launch("disc-9", "apr-1", ESTIMATE, AT),
            "R5",
            id="unknown-disc",
        ),
    ],
)
def test_refused_launch_reports_the_rule_and_changes_nothing(
    make_store: MakeStore, seed: Seed, launch: Launch, rule: str
) -> None:
    store = make_store(DISCS, seed.approvals, seed.disc_spend, seed.month_spend)
    before = state(store)

    result = store.record_launch(launch, LIMITS)

    assert result.launched is False
    assert result.rule == rule
    assert state(store) == before


def test_estimate_over_a_monthly_cap_with_no_spend_yet_is_refused(make_store: MakeStore) -> None:
    store = make_store(DISCS, [APPROVAL])

    result = store.record_launch(LAUNCH, Limits(monthly_cap_usd=Decimal("0.19")))

    assert result.rule == "R3"
    assert store.snapshot(AT).month_spend_usd == Decimal("0")


def test_second_launch_with_the_same_approval_is_refused_A5(make_store: MakeStore) -> None:  # noqa: N802  # stress case id
    store = make_store(DISCS, [APPROVAL])
    assert store.record_launch(LAUNCH, LIMITS).launched is True
    after_first = state(store)

    again = store.record_launch(dataclasses.replace(LAUNCH, at=AT + timedelta(seconds=1)), LIMITS)

    assert again.launched is False
    assert again.rule == "R4"
    assert state(store) == after_first


def test_two_launches_that_together_exceed_the_disc_cap_A4(make_store: MakeStore) -> None:  # noqa: N802  # stress case id
    part = Decimal("0.60")
    approvals = [approval(ref="apr-1", approved_usd=part), approval(ref="apr-2", approved_usd=part)]
    store = make_store(DISCS, approvals)

    first = store.record_launch(Launch("disc-1", "apr-1", part, AT), LIMITS)
    second = store.record_launch(Launch("disc-1", "apr-2", part, AT), LIMITS)

    assert first.launched is True
    assert second.rule == "R2"
    snapshot = store.snapshot(AT)
    assert snapshot.disc_spend_usd == {"disc-1": part}
    assert [a.consumed for a in snapshot.approvals] == [True, False]


def test_two_launches_that_together_exceed_the_monthly_cap(make_store: MakeStore) -> None:
    approvals = [APPROVAL, approval(ref="apr-2", disc_id="disc-2")]
    store = make_store(DISCS, approvals, {}, {MONTH: Decimal("4.70")})

    first = store.record_launch(LAUNCH, LIMITS)
    second = store.record_launch(Launch("disc-2", "apr-2", ESTIMATE, AT), LIMITS)

    assert first.launched is True
    assert second.rule == "R3"
    assert store.snapshot(AT).month_spend_usd == Decimal("4.90")


@pytest.mark.parametrize(
    ("disc_spend", "month_spend"),
    [
        pytest.param({"disc-1": Decimal("0.80")}, {}, id="disc-total-exactly-1.00"),
        pytest.param({}, {MONTH: Decimal("4.80")}, id="month-total-exactly-5.00"),
        pytest.param(
            {"disc-1": Decimal("0.80")}, {MONTH: Decimal("4.80")}, id="both-exactly-at-the-cap"
        ),
    ],
)
def test_launch_reaching_exactly_a_cap_is_recorded(
    make_store: MakeStore, disc_spend: dict[str, Decimal], month_spend: dict[str, Decimal]
) -> None:
    store = make_store(DISCS, [APPROVAL], disc_spend, month_spend)

    assert store.record_launch(LAUNCH, LIMITS).launched is True


def test_estimate_of_exactly_the_disc_cap_is_recorded_on_a_fresh_disc(
    make_store: MakeStore,
) -> None:
    store = make_store(DISCS, [approval(approved_usd=Decimal("1.00"))])

    result = store.record_launch(Launch("disc-1", "apr-1", Decimal("1.00"), AT), LIMITS)

    assert result.launched is True


def test_launch_counts_against_the_utc_month_of_its_time(make_store: MakeStore) -> None:
    store = make_store(DISCS, [APPROVAL], {}, {MONTH: Decimal("5.00")})
    december = datetime(2026, 12, 1, 0, 0, tzinfo=UTC)

    result = store.record_launch(dataclasses.replace(LAUNCH, at=december), LIMITS)

    assert result.launched is True
    assert store.snapshot(december).month_spend_usd == ESTIMATE
    assert store.snapshot(AT).month_spend_usd == Decimal("5.00")


def test_launch_with_malformed_limits_is_rejected_and_changes_nothing(
    make_store: MakeStore,
) -> None:
    store = make_store(DISCS, [APPROVAL])
    before = state(store)

    with pytest.raises(InvalidLedgerInputError, match="limits is malformed"):
        store.record_launch(LAUNCH, Limits(monthly_cap_usd=Decimal("NaN")))

    assert state(store) == before


def test_approval_request_is_pending_and_leaves_an_event(make_store: MakeStore) -> None:
    store = make_store(DISCS)

    store.create_approval_request("disc-1", ESTIMATE, "apr-1", AT)

    pending = approval(status="pending")
    assert store.pending_approvals() == (pending,)
    assert store.snapshot(AT).approvals == (pending,)
    (event,) = store.recent_events(10)
    assert event.type == "approval_requested"
    assert event.at == AT
    assert event.detail == {"disc_id": "disc-1", "approval_ref": "apr-1", "approved_usd": ESTIMATE}


def test_pending_approval_does_not_allow_a_launch(make_store: MakeStore) -> None:
    store = make_store(DISCS)
    store.create_approval_request("disc-1", ESTIMATE, "apr-1", AT)

    assert store.record_launch(LAUNCH, LIMITS).rule == "R4"


@pytest.mark.parametrize(
    ("disc_id", "ref", "error"),
    [
        pytest.param("disc-2", "apr-1", ApprovalRefExistsError, id="duplicate-ref"),
        pytest.param("disc-1", "apr-2", PendingApprovalExistsError, id="second-pending-for-disc"),
        pytest.param("disc-9", "apr-2", UnknownDiscError, id="unknown-disc"),
        pytest.param("disc-9", "apr-1", ApprovalRefExistsError, id="duplicate-ref-wins"),
    ],
)
def test_refused_approval_request_changes_nothing(
    make_store: MakeStore, disc_id: str, ref: str, error: type[Exception]
) -> None:
    store = make_store(DISCS)
    store.create_approval_request("disc-1", ESTIMATE, "apr-1", AT)
    before = state(store)

    with pytest.raises(error):
        store.create_approval_request(disc_id, ESTIMATE, ref, AT + timedelta(minutes=1))

    assert state(store) == before


def test_seeded_pending_approval_blocks_another_request_for_its_disc(
    make_store: MakeStore,
) -> None:
    store = make_store(DISCS, [approval(status="pending")])

    with pytest.raises(PendingApprovalExistsError):
        store.create_approval_request("disc-1", ESTIMATE, "apr-2", AT)


def test_another_disc_can_still_be_requested(make_store: MakeStore) -> None:
    store = make_store(DISCS)
    store.create_approval_request("disc-1", ESTIMATE, "apr-1", AT)

    store.create_approval_request("disc-2", ESTIMATE, "apr-2", AT)

    assert [a.ref for a in store.pending_approvals()] == ["apr-1", "apr-2"]


def test_pending_approvals_exclude_decided_ones(make_store: MakeStore) -> None:
    approvals = [
        approval(ref="apr-3", status="pending", disc_id="disc-2"),
        approval(ref="apr-1"),
        approval(ref="apr-2", status="rejected"),
    ]
    store = make_store(DISCS, approvals)

    assert [a.ref for a in store.pending_approvals()] == ["apr-3"]


@pytest.mark.parametrize(
    ("disc_id", "approved_usd", "ref", "at"),
    [
        pytest.param("Disc 1", ESTIMATE, "apr-1", AT, id="malformed-disc_id"),
        pytest.param("disc-1", ESTIMATE, "apr 1", AT, id="malformed-ref"),
        pytest.param("disc-1", Decimal("-1"), "apr-1", AT, id="negative-amount"),
        pytest.param("disc-1", ESTIMATE, "apr-1", AT.replace(tzinfo=None), id="naive-time"),
    ],
)
def test_malformed_approval_request_is_rejected_and_changes_nothing(
    make_store: MakeStore, disc_id: str, approved_usd: Decimal, ref: str, at: datetime
) -> None:
    store = make_store(DISCS)

    with pytest.raises(InvalidLedgerInputError):
        store.create_approval_request(disc_id, approved_usd, ref, at)

    assert state(store) == (store.snapshot(AT), ())
    assert store.pending_approvals() == ()


def test_approved_request_is_not_consumed_and_allows_one_launch(make_store: MakeStore) -> None:
    store = make_store(DISCS)
    store.create_approval_request("disc-1", ESTIMATE, "apr-1", AT)

    decided = store.decide_approval("apr-1", True, DECIDED_AT)

    snapshot, events = state(store)
    assert decided == DecidedApproval("apr-1", "disc-1", "approved")
    assert snapshot.approvals == (APPROVAL,)
    assert store.pending_approvals() == ()
    assert (snapshot.month_spend_usd, snapshot.disc_spend_usd) == (Decimal("0"), {})
    assert events[0] == LedgerEvent(
        at=DECIDED_AT,
        event_id="approval_decided:apr-1",
        type="approval_decided",
        detail={"disc_id": "disc-1", "approval_ref": "apr-1", "decision": "approved"},
    )
    assert [event.type for event in events] == ["approval_decided", "approval_requested"]
    assert store.record_launch(LAUNCH_AFTER_DECISION, LIMITS).launched is True
    assert store.snapshot(AT).approvals == (approval(consumed=True),)
    again = dataclasses.replace(LAUNCH_AFTER_DECISION, at=AT + timedelta(minutes=3))
    assert store.record_launch(again, LIMITS).rule == "R4"


def test_rejected_request_is_not_consumed_and_allows_no_launch(make_store: MakeStore) -> None:
    store = make_store(DISCS)
    store.create_approval_request("disc-1", ESTIMATE, "apr-1", AT)

    decided = store.decide_approval("apr-1", False, DECIDED_AT)

    rejected = approval(status="rejected")
    assert decided == DecidedApproval("apr-1", "disc-1", "rejected")
    assert store.snapshot(AT).approvals == (rejected,)
    assert store.pending_approvals() == ()
    assert store.recent_events(1)[0].detail == {
        "disc_id": "disc-1",
        "approval_ref": "apr-1",
        "decision": "rejected",
    }
    after_decision = state(store)
    assert store.record_launch(LAUNCH_AFTER_DECISION, LIMITS).rule == "R4"
    assert state(store) == after_decision


@pytest.mark.parametrize("approved", [True, False])
@pytest.mark.parametrize(
    ("approvals", "error"),
    [
        pytest.param([approval(ref="apr-2", status="pending")], UnknownApprovalError, id="unknown"),
        pytest.param([], UnknownApprovalError, id="empty-ledger"),
        pytest.param([APPROVAL], ApprovalNotPendingError, id="already-approved"),
        pytest.param([approval(status="rejected")], ApprovalNotPendingError, id="already-rejected"),
        pytest.param([approval(consumed=True)], ApprovalNotPendingError, id="approved-consumed"),
        pytest.param(
            [approval(status="pending", consumed=True)],
            ApprovalNotPendingError,
            id="pending-but-consumed",
        ),
        pytest.param(
            [PENDING, approval(ref="apr-2", status="pending")],
            ApprovalDiscMismatchError,
            id="disc-marked-with-another-request",
        ),
        pytest.param(
            [approval(status="pending", disc_id="disc-9")],
            ApprovalDiscMismatchError,
            id="disc-not-in-the-ledger",
        ),
        pytest.param(
            [approval(status="pending", disc_id="Disc 1")],
            LedgerDataError,
            id="held-disc-id-is-not-an-identifier",
        ),
    ],
)
def test_refused_decision_raises_its_error_and_changes_nothing(
    make_store: MakeStore, approvals: list[Approval], error: type[Exception], approved: bool
) -> None:
    store = make_store(DISCS, approvals)
    before = state(store)
    pending = store.pending_approvals()

    with pytest.raises(error):
        store.decide_approval("apr-1", approved, DECIDED_AT)

    assert state(store) == before
    assert store.pending_approvals() == pending


@pytest.mark.parametrize(("first", "second"), [(True, False), (False, True), (True, True)])
def test_decided_request_cannot_be_decided_again(
    make_store: MakeStore, first: bool, second: bool
) -> None:
    store = make_store(DISCS, [PENDING])
    store.decide_approval("apr-1", first, DECIDED_AT)
    after_first = state(store)

    with pytest.raises(ApprovalNotPendingError):
        store.decide_approval("apr-1", second, DECIDED_AT + timedelta(minutes=1))

    assert state(store) == after_first


def test_launched_approval_cannot_be_decided(make_store: MakeStore) -> None:
    store = make_store(DISCS, [PENDING])
    store.decide_approval("apr-1", True, DECIDED_AT)
    store.record_launch(LAUNCH_AFTER_DECISION, LIMITS)
    after_launch = state(store)

    with pytest.raises(ApprovalNotPendingError):
        store.decide_approval("apr-1", False, AT + timedelta(minutes=3))

    assert state(store) == after_launch


@pytest.mark.parametrize("approved", [True, False])
def test_disc_can_be_requested_again_after_a_decision_R6(  # noqa: N802  # rule id
    make_store: MakeStore, approved: bool
) -> None:
    store = make_store(DISCS, [PENDING])
    with pytest.raises(PendingApprovalExistsError):
        store.create_approval_request("disc-1", ESTIMATE, "apr-2", AT)

    store.decide_approval("apr-1", approved, DECIDED_AT)
    store.create_approval_request("disc-1", ESTIMATE, "apr-2", AT + timedelta(minutes=2))

    assert [a.ref for a in store.pending_approvals()] == ["apr-2"]
    with pytest.raises(PendingApprovalExistsError):
        store.create_approval_request("disc-1", ESTIMATE, "apr-3", AT + timedelta(minutes=3))
    assert store.decide_approval("apr-2", True, AT + timedelta(minutes=4)).status == "approved"
    assert store.pending_approvals() == ()


def test_decision_leaves_the_request_of_another_disc_pending(make_store: MakeStore) -> None:
    other = approval(ref="apr-2", disc_id="disc-2", status="pending")
    store = make_store(DISCS, [PENDING, other])

    store.decide_approval("apr-1", False, DECIDED_AT)

    assert store.pending_approvals() == (other,)
    with pytest.raises(PendingApprovalExistsError):
        store.create_approval_request("disc-2", ESTIMATE, "apr-3", AT)


@pytest.mark.parametrize(
    ("ref", "approved", "at"),
    [
        pytest.param("apr 1", True, DECIDED_AT, id="malformed-ref"),
        pytest.param("apr-1", "yes", DECIDED_AT, id="truthy-string"),
        pytest.param("apr-1", 1, DECIDED_AT, id="one-is-not-true"),
        pytest.param("apr-1", None, DECIDED_AT, id="none"),
        pytest.param("apr-1", True, DECIDED_AT.replace(tzinfo=None), id="naive-time"),
    ],
)
def test_malformed_decision_is_rejected_and_changes_nothing(
    make_store: MakeStore, ref: str, approved: bool, at: datetime
) -> None:
    store = make_store(DISCS, [PENDING])
    before = state(store)

    with pytest.raises(InvalidLedgerInputError):
        store.decide_approval(ref, approved, at)

    assert state(store) == before
    assert store.pending_approvals() == (PENDING,)


def decide_together(store: LedgerStore, ref: str) -> list[DecisionOutcome]:
    """Approve and reject `ref` from two threads released at the same moment."""
    barrier = threading.Barrier(2)

    def attempt(approved: bool) -> DecisionOutcome:
        barrier.wait(timeout=BARRIER_TIMEOUT_SECONDS)
        # Different times give different events, so only the approval can stop the loser.
        at = DECIDED_AT + timedelta(seconds=int(approved))
        try:
            return store.decide_approval(ref, approved, at)
        except (ApprovalNotPendingError, LedgerTransactionError) as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(attempt, [True, False]))


def test_two_concurrent_decisions_on_one_request_at_most_one_wins(make_store: MakeStore) -> None:
    """Race an approval against a rejection, several times: at most one wins, never both.

    DynamoDB may cancel both colliding transactions as conflicts, so a round can
    have no winner. The ledger must then be as it was: nothing half decided.
    """
    discs = [Disc(f"disc-{number}", 600) for number in range(1, RACE_ROUNDS + 1)]
    requests = [
        approval(ref=f"apr-{number}", disc_id=f"disc-{number}", status="pending")
        for number in range(1, RACE_ROUNDS + 1)
    ]
    store = make_store(discs, requests)

    for request in requests:
        outcomes = decide_together(store, request.ref)

        winners = [o for o in outcomes if isinstance(o, DecidedApproval)]
        refused = [o for o in outcomes if isinstance(o, ApprovalNotPendingError)]
        held = {a.ref: a for a in store.snapshot(AT).approvals}[request.ref]
        logged = [
            event.detail
            for event in store.recent_events(100)
            if event.event_id == f"approval_decided:{request.ref}"
        ]
        retry_ref, retry_at = f"{request.ref}-retry", AT + timedelta(hours=1)
        assert len(winners) <= 1
        assert held.consumed is False
        if winners:
            decision = winners[0].status
            assert held.status == decision
            assert logged == [
                {"disc_id": request.disc_id, "approval_ref": request.ref, "decision": decision}
            ]
            # The mark is cleared: the disc accepts a new request.
            store.create_approval_request(request.disc_id, ESTIMATE, retry_ref, retry_at)
        else:
            # Nobody decided, so nobody can have been told that somebody else did.
            assert refused == []
            assert held == request
            assert logged == []
            # The mark is unchanged: the disc still refuses a new request.
            with pytest.raises(PendingApprovalExistsError):
                store.create_approval_request(request.disc_id, ESTIMATE, retry_ref, retry_at)
        assert (request in store.pending_approvals()) is not bool(winners)


def test_recent_events_are_newest_first_and_limited(make_store: MakeStore) -> None:
    store = make_store(DISCS, [APPROVAL])
    store.create_approval_request("disc-2", ESTIMATE, "apr-2", AT - timedelta(hours=1))
    store.record_launch(LAUNCH, LIMITS)
    store.create_approval_request("disc-1", ESTIMATE, "apr-3", AT + timedelta(hours=1))

    assert [e.event_id for e in store.recent_events(10)] == [
        "approval_requested:apr-3",
        "job_launched:apr-1",
        "approval_requested:apr-2",
    ]
    assert [e.event_id for e in store.recent_events(2)] == [
        "approval_requested:apr-3",
        "job_launched:apr-1",
    ]


@pytest.mark.parametrize("limit", [0, -1])
def test_recent_events_reject_a_limit_below_one(make_store: MakeStore, limit: int) -> None:
    with pytest.raises(InvalidLedgerInputError, match="limit is malformed"):
        make_store().recent_events(limit)


def test_snapshot_rejects_a_naive_time(make_store: MakeStore) -> None:
    with pytest.raises(InvalidLedgerInputError, match="at is malformed"):
        make_store().snapshot(AT.replace(tzinfo=None))


def test_snapshot_reads_the_spend_of_the_utc_month_of_its_time(make_store: MakeStore) -> None:
    store = make_store(DISCS, [], {}, {"2026-11": Decimal("1.25"), "2026-12": Decimal("0.40")})
    local_december = datetime(2026, 12, 1, 0, 30, tzinfo=timezone(timedelta(hours=2)))
    local_november = datetime(2026, 11, 30, 20, 0, tzinfo=timezone(timedelta(hours=-6)))

    assert store.snapshot(local_december).month_spend_usd == Decimal("1.25")
    assert store.snapshot(local_november).month_spend_usd == Decimal("0.40")


def test_empty_ledger_gives_an_empty_well_formed_snapshot(make_store: MakeStore) -> None:
    snapshot = make_store().snapshot(AT)

    assert snapshot == LedgerSnapshot((), (), Decimal("0"), {})
    assert is_well_formed_snapshot(snapshot)


def test_snapshot_round_trips_what_was_seeded(make_store: MakeStore) -> None:
    approvals = [approval(ref="apr-2", status="rejected"), APPROVAL]
    store = make_store(DISCS, approvals, {"disc-2": Decimal("0.40")}, {MONTH: Decimal("1.25")})

    snapshot = store.snapshot(AT)

    assert snapshot == LedgerSnapshot(
        discs=DISCS,
        approvals=(APPROVAL, approval(ref="apr-2", status="rejected")),
        month_spend_usd=Decimal("1.25"),
        disc_spend_usd={"disc-2": Decimal("0.40")},
    )
    assert is_well_formed_snapshot(snapshot)
    assert store.snapshot(AT - timedelta(days=31)).month_spend_usd == Decimal("0")


def test_snapshot_stays_well_formed_after_writes(make_store: MakeStore) -> None:
    store = make_store(DISCS, [APPROVAL])
    store.record_launch(LAUNCH, LIMITS)
    store.create_approval_request("disc-2", ESTIMATE, "apr-2", AT)

    assert is_well_formed_snapshot(store.snapshot(AT))


def test_amounts_stay_decimal_end_to_end(make_store: MakeStore) -> None:
    store = make_store(DISCS, [APPROVAL], {"disc-2": Decimal("0.10")}, {MONTH: Decimal("0.10")})
    store.record_launch(LAUNCH, LIMITS)
    store.create_approval_request("disc-2", Decimal("0.30"), "apr-2", AT)

    snapshot, events = state(store)
    amounts = [
        snapshot.month_spend_usd,
        *snapshot.disc_spend_usd.values(),
        *(a.approved_usd for a in snapshot.approvals),
        *(a.approved_usd for a in store.pending_approvals()),
        *(e.detail[key] for e in events for key in e.detail if key.endswith("_usd")),
    ]
    assert len(amounts) == 8
    assert all(type(amount) is Decimal for amount in amounts)
    assert snapshot.month_spend_usd == Decimal("0.30")
    assert str(snapshot.disc_spend_usd["disc-1"]) == "0.20"


def test_amounts_are_returned_in_whole_cents_with_two_decimal_places(make_store: MakeStore) -> None:
    tenth = Decimal("0.1")
    approvals = [approval(approved_usd=Decimal("0.2")), approval(ref="apr-2", status="pending")]
    store = make_store(DISCS, approvals, {"disc-2": tenth}, {MONTH: Decimal("1")})
    store.record_launch(Launch("disc-1", "apr-1", Decimal("0.2"), AT), LIMITS)
    store.create_approval_request("disc-2", Decimal("0.3"), "apr-3", AT + timedelta(minutes=1))

    snapshot, events = state(store)
    assert str(snapshot.month_spend_usd) == "1.20"
    assert {disc: str(spent) for disc, spent in snapshot.disc_spend_usd.items()} == {
        "disc-1": "0.20",
        "disc-2": "0.10",
    }
    assert [str(a.approved_usd) for a in snapshot.approvals] == ["0.20", "0.20", "0.30"]
    assert [str(a.approved_usd) for a in store.pending_approvals()] == ["0.20", "0.30"]
    assert [str(e.detail[key]) for e in events for key in e.detail if key.endswith("_usd")] == [
        "0.30",
        "0.20",
    ]


def test_month_with_no_spend_reads_as_zero_in_two_decimal_places(make_store: MakeStore) -> None:
    assert str(make_store(DISCS).snapshot(AT).month_spend_usd) == "0.00"


@pytest.mark.parametrize(
    ("approvals", "disc_spend", "month_spend"),
    [
        pytest.param([approval(approved_usd=Decimal("0.205"))], {}, {}, id="approved-amount"),
        pytest.param([], {"disc-1": Decimal("0.205")}, {}, id="disc-spend"),
        pytest.param([], {}, {MONTH: Decimal("0.205")}, id="month-spend"),
    ],
)
def test_held_amount_that_is_not_whole_cents_stops_a_snapshot(
    make_store: MakeStore,
    approvals: list[Approval],
    disc_spend: dict[str, Decimal],
    month_spend: dict[str, Decimal],
) -> None:
    store = make_store(DISCS, approvals, disc_spend, month_spend)

    with pytest.raises(LedgerDataError, match="_usd"):
        store.snapshot(AT)


@pytest.mark.parametrize(
    ("approvals", "disc_spend", "month_spend", "disc_id"),
    [
        pytest.param([APPROVAL], {}, {}, "disc-1", id="allowed"),
        pytest.param([APPROVAL], {"disc-1": Decimal("0.80")}, {}, "disc-1", id="at-the-disc-cap"),
        pytest.param([APPROVAL], {"disc-1": Decimal("0.81")}, {}, "disc-1", id="R2"),
        pytest.param([APPROVAL], {}, {MONTH: Decimal("4.81")}, "disc-1", id="R3"),
        pytest.param([approval(consumed=True)], {}, {}, "disc-1", id="R4-consumed"),
        pytest.param([approval(status="pending")], {}, {}, "disc-1", id="R4-pending"),
        pytest.param([], {}, {}, "disc-1", id="R4-missing"),
        pytest.param([approval(disc_id="disc-2")], {}, {}, "disc-1", id="R4-other-disc"),
        pytest.param(
            [],
            {"disc-1": Decimal("0.90")},
            {MONTH: Decimal("4.90")},
            "disc-1",
            id="R2-first-when-every-rule-fails",
        ),
        pytest.param([], {}, {MONTH: Decimal("4.90")}, "disc-1", id="R3-before-R4"),
        pytest.param([approval(disc_id="disc-9")], {}, {}, "disc-9", id="R5-unknown-disc"),
    ],
)
def test_gate_and_store_agree_on_the_same_state(
    make_store: MakeStore,
    approvals: list[Approval],
    disc_spend: dict[str, Decimal],
    month_spend: dict[str, Decimal],
    disc_id: str,
) -> None:
    store = make_store(DISCS, approvals, disc_spend, month_spend)
    call = ToolCall("launch_job", {"disc_id": disc_id, "approval_ref": "apr-1"})
    estimate = estimate_cost(DISC.duration_seconds, LIMITS.usd_per_minute)

    decision = evaluate(call, store.snapshot(AT), LIMITS)
    result = store.record_launch(Launch(disc_id, "apr-1", estimate, AT), LIMITS)

    assert (result.launched, result.rule) == (decision.allowed, decision.rule)


def test_store_exposes_only_the_protocol_operations(make_store: MakeStore) -> None:
    public = {name for name in dir(make_store()) if not name.startswith("_")}

    assert public == {
        "snapshot",
        "recent_events",
        "pending_approvals",
        "create_approval_request",
        "decide_approval",
        "record_launch",
    }
