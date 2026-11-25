from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fareguard.gate.models import Approval, Disc, Limits
from fareguard.ledger.errors import LedgerError
from fareguard.ledger.memory import InMemoryLedgerStore
from fareguard.ledger.store import Launch, LaunchResult, LedgerStore

AT = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)
MONTH = "2026-11"
LIMITS = Limits()
ESTIMATE = Decimal("0.20")
DISCS = [Disc(f"disc-{number}", 600) for number in range(1, 9)]
WORKERS = 8


def approval(ref: str, disc_id: str) -> Approval:
    return Approval(ref, "launch_job", disc_id, ESTIMATE, "approved", False)


def test_in_memory_store_satisfies_the_protocol() -> None:
    store: LedgerStore = InMemoryLedgerStore()

    assert store.pending_approvals() == ()


def test_only_one_of_many_concurrent_launches_consumes_an_approval() -> None:
    store = InMemoryLedgerStore(DISCS, [approval("apr-1", "disc-1")])

    def launch(second: int) -> LaunchResult:
        at = AT + timedelta(seconds=second)
        return store.record_launch(Launch("disc-1", "apr-1", ESTIMATE, at), LIMITS)

    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(launch, range(WORKERS * 5)))

    assert sum(result.launched for result in results) == 1
    assert {result.rule for result in results if not result.launched} == {"R4"}
    assert store.snapshot(MONTH).month_spend_usd == ESTIMATE
    assert len(store.recent_events(100)) == 1


def test_concurrent_launches_never_exceed_the_monthly_cap() -> None:
    approvals = [approval(f"apr-{disc.disc_id}", disc.disc_id) for disc in DISCS]
    store = InMemoryLedgerStore(DISCS, approvals, None, {MONTH: Decimal("4.50")})

    def launch(disc: Disc) -> LaunchResult:
        return store.record_launch(
            Launch(disc.disc_id, f"apr-{disc.disc_id}", ESTIMATE, AT), LIMITS
        )

    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(launch, DISCS))

    assert sum(result.launched for result in results) == 2
    assert {result.rule for result in results if not result.launched} == {"R3"}
    assert store.snapshot(MONTH).month_spend_usd == Decimal("4.90")


def test_only_one_of_many_concurrent_requests_for_a_disc_is_recorded() -> None:
    store = InMemoryLedgerStore(DISCS)

    def request(number: int) -> bool:
        try:
            store.create_approval_request("disc-1", ESTIMATE, f"apr-{number}", AT)
        except LedgerError:
            return False
        return True

    with ThreadPoolExecutor(WORKERS) as pool:
        recorded = list(pool.map(request, range(WORKERS * 5)))

    assert sum(recorded) == 1
    assert len(store.pending_approvals()) == 1


def test_changing_a_returned_snapshot_does_not_change_the_store() -> None:
    seed = {"disc-1": Decimal("0.10")}
    store = InMemoryLedgerStore(DISCS, [], seed)
    snapshot = store.snapshot(MONTH)

    assert isinstance(snapshot.disc_spend_usd, dict)
    snapshot.disc_spend_usd["disc-1"] = Decimal("0.00")
    seed["disc-1"] = Decimal("9.99")

    assert store.snapshot(MONTH).disc_spend_usd == {"disc-1": Decimal("0.10")}
