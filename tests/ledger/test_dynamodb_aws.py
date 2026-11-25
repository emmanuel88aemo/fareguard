"""What only real DynamoDB can settle about the DynamoDB ledger store.

These tests run on a temporary table in real DynamoDB and are skipped unless
FAREGUARD_RUN_AWS_TESTS is "1". They cover the behaviour the store relies on
and moto could not confirm: the cancellation reasons of a transaction whose
conditions fail together, reserved words in expressions, and concurrent launches.
"""

import dataclasses
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fareguard.gate.models import Approval, Disc, Limits
from fareguard.ledger.errors import LedgerTransactionError
from fareguard.ledger.store import Launch, LaunchResult, LedgerEvent, LedgerStore, month_of

pytestmark = pytest.mark.aws

type MakeStore = Callable[..., LedgerStore]
# A launch that loses a race is refused by its condition or cancelled as a conflict.
type Outcome = LaunchResult | LedgerTransactionError

AT = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)
MONTH = month_of(AT)
LIMITS = Limits()
ESTIMATE = Decimal("0.20")
DISCS = (Disc("disc-1", 600), Disc("disc-2", 600))
APPROVAL = Approval("apr-1", "launch_job", "disc-1", ESTIMATE, "approved", False)
LAUNCH = Launch("disc-1", "apr-1", ESTIMATE, AT)
UNKNOWN_DISC_LAUNCH = Launch("disc-9", "apr-1", ESTIMATE, AT)
OVER_THE_DISC_CAP = {"disc-1": Decimal("0.90")}
OVER_THE_MONTHLY_CAP = {MONTH: Decimal("4.90")}
BARRIER_TIMEOUT_SECONDS = 30


def events(store: LedgerStore) -> tuple[LedgerEvent, ...]:
    return store.recent_events(100)


def launch_together(
    store: LedgerStore, launches: Sequence[Launch], limits: Limits
) -> list[Outcome]:
    """Record every launch from its own thread, all released at the same moment."""
    barrier = threading.Barrier(len(launches))

    def attempt(launch: Launch) -> Outcome:
        barrier.wait(timeout=BARRIER_TIMEOUT_SECONDS)
        try:
            return store.record_launch(launch, limits)
        except LedgerTransactionError as error:
            return error

    with ThreadPoolExecutor(max_workers=len(launches)) as pool:
        return list(pool.map(attempt, launches))


def recorded(outcomes: Sequence[Outcome]) -> list[LaunchResult]:
    return [o for o in outcomes if isinstance(o, LaunchResult) and o.launched]


def refusal_rules(outcomes: Sequence[Outcome]) -> set[str | None]:
    return {o.rule for o in outcomes if isinstance(o, LaunchResult) and not o.launched}


@dataclasses.dataclass(frozen=True)
class Seed:
    """What the table holds before the launch under test."""

    approvals: tuple[Approval, ...] = ()
    disc_spend: Mapping[str, Decimal] = dataclasses.field(default_factory=dict)
    month_spend: Mapping[str, Decimal] = dataclasses.field(default_factory=dict)


@pytest.mark.parametrize(
    ("seed", "launch", "rule"),
    [
        pytest.param(
            Seed((), OVER_THE_DISC_CAP, OVER_THE_MONTHLY_CAP), LAUNCH, "R2", id="R2-R3-R4-fail"
        ),
        pytest.param(Seed((), OVER_THE_DISC_CAP), LAUNCH, "R2", id="R2-R4-fail"),
        pytest.param(
            Seed((APPROVAL,), OVER_THE_DISC_CAP, OVER_THE_MONTHLY_CAP),
            LAUNCH,
            "R2",
            id="R2-R3-fail",
        ),
        pytest.param(Seed(month_spend=OVER_THE_MONTHLY_CAP), LAUNCH, "R3", id="R3-R4-fail"),
        pytest.param(
            Seed(month_spend=OVER_THE_MONTHLY_CAP),
            UNKNOWN_DISC_LAUNCH,
            "R5",
            id="unknown-disc-R3-R4-fail",
        ),
    ],
)
def test_several_failed_conditions_report_the_first_rule_in_the_gate_order(
    make_aws_store: MakeStore, seed: Seed, launch: Launch, rule: str
) -> None:
    store = make_aws_store(DISCS, seed.approvals, seed.disc_spend, seed.month_spend)
    before = store.snapshot(AT)

    result = store.record_launch(launch, LIMITS)

    assert (result.launched, result.rule) == (False, rule)
    assert store.snapshot(AT) == before
    assert events(store) == ()


def test_replayed_launch_reports_the_consumed_approval_before_the_duplicate_event(
    make_aws_store: MakeStore,
) -> None:
    store = make_aws_store(DISCS, [APPROVAL])
    assert store.record_launch(LAUNCH, LIMITS).launched is True
    after_first = store.snapshot(AT)

    again = store.record_launch(LAUNCH, LIMITS)

    assert (again.launched, again.rule) == (False, "R4")
    assert store.snapshot(AT) == after_first
    assert events(store) == (LAUNCH.event(),)


def test_unknown_disc_is_reported_as_R5(make_aws_store: MakeStore) -> None:  # noqa: N802  # rule id
    approval = dataclasses.replace(APPROVAL, disc_id="disc-9")
    store = make_aws_store(DISCS, [approval])

    result = store.record_launch(UNKNOWN_DISC_LAUNCH, LIMITS)

    assert (result.launched, result.rule) == (False, "R5")
    assert "the disc is not in the ledger" in result.reason
    assert store.snapshot(AT).approvals == (approval,)


@pytest.mark.parametrize(
    ("disc_spend", "estimate"),
    [
        pytest.param({"disc-1": Decimal("0.81")}, ESTIMATE, id="spend-plus-estimate-over-the-cap"),
        pytest.param({}, Decimal("1.50"), id="A3-no-spend-yet-and-estimate-over-the-cap"),
    ],
)
def test_over_cap_disc_is_reported_as_R2(  # noqa: N802  # rule id
    make_aws_store: MakeStore, disc_spend: dict[str, Decimal], estimate: Decimal
) -> None:
    approval = dataclasses.replace(APPROVAL, approved_usd=estimate)
    store = make_aws_store(DISCS, [approval], disc_spend)

    result = store.record_launch(Launch("disc-1", "apr-1", estimate, AT), LIMITS)

    assert (result.launched, result.rule) == (False, "R2")
    assert store.snapshot(AT).disc_spend_usd == disc_spend


def test_every_expression_is_accepted_without_a_reserved_word_error(
    make_aws_store: MakeStore,
) -> None:
    """Run every expression the store sends, in each of its variants.

    DynamoDB rejects a reserved word used as an attribute name with a
    ValidationException before it evaluates any condition, and the store lets
    that error through, so reaching the assertions is the evidence.
    """
    second = dataclasses.replace(APPROVAL, ref="apr-2")
    store = make_aws_store(DISCS, [APPROVAL, second])
    below_the_estimate = Limits(max_usd_per_disc=Decimal("0.10"), monthly_cap_usd=Decimal("0.10"))

    store.create_approval_request("disc-2", ESTIMATE, "apr-3", AT)
    # Caps below the estimate: the cap conditions without attribute_not_exists.
    cap_only = store.record_launch(LAUNCH, below_the_estimate)
    # No spend yet, then spend already stored: both sides of the cap condition.
    first = store.record_launch(LAUNCH, LIMITS)
    later = store.record_launch(Launch("disc-1", "apr-2", ESTIMATE, AT), LIMITS)

    assert cap_only.rule == "R2"
    assert (first.launched, later.launched) == (True, True)
    assert store.snapshot(AT).month_spend_usd == ESTIMATE * 2
    assert [a.ref for a in store.pending_approvals()] == ["apr-3"]
    assert len(store.recent_events(2)) == 2


def test_same_approval_launched_from_two_threads_is_recorded_once(
    make_aws_store: MakeStore,
) -> None:
    store = make_aws_store(DISCS, [APPROVAL])
    # Different times give different events, so only the approval can stop the second launch.
    launches = [LAUNCH, dataclasses.replace(LAUNCH, at=AT + timedelta(seconds=1))]

    outcomes = launch_together(store, launches, LIMITS)

    assert len(recorded(outcomes)) == 1
    assert refusal_rules(outcomes) <= {"R4"}
    snapshot = store.snapshot(AT)
    assert snapshot.approvals == (dataclasses.replace(APPROVAL, consumed=True),)
    assert snapshot.disc_spend_usd == {"disc-1": ESTIMATE}
    assert snapshot.month_spend_usd == ESTIMATE
    assert [event.type for event in events(store)] == ["job_launched"]


def test_twenty_concurrent_launches_never_push_the_spend_over_the_monthly_cap(
    make_aws_store: MakeStore,
) -> None:
    cap = Decimal("1.00")
    discs = [Disc(f"disc-{number}", 600) for number in range(1, 21)]
    approvals = [
        dataclasses.replace(APPROVAL, ref=f"apr-{disc.disc_id}", disc_id=disc.disc_id)
        for disc in discs
    ]
    launches = [Launch(a.disc_id, a.ref, ESTIMATE, AT) for a in approvals]
    store = make_aws_store(discs, approvals)
    assert ESTIMATE * len(launches) > cap

    outcomes = launch_together(store, launches, Limits(monthly_cap_usd=cap))

    launched = len(recorded(outcomes))
    snapshot = store.snapshot(AT)
    assert snapshot.month_spend_usd <= cap
    assert snapshot.month_spend_usd == ESTIMATE * launched
    assert 1 <= launched <= cap / ESTIMATE
    assert refusal_rules(outcomes) <= {"R3"}
    assert sum(snapshot.disc_spend_usd.values()) == snapshot.month_spend_usd
    assert sum(approval.consumed for approval in snapshot.approvals) == launched
    assert len(events(store)) == launched
