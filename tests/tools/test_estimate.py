from datetime import UTC, datetime
from decimal import Decimal

from fareguard.gate.models import Disc, Limits
from fareguard.ledger.memory import InMemoryLedgerStore
from fareguard.tools.estimate import estimate_disc

NOW = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)
SNAPSHOT = InMemoryLedgerStore([Disc("disc-1", 600), Disc("disc-empty", 0)]).snapshot(NOW)


def test_estimate_comes_from_the_duration_of_the_disc() -> None:
    assert estimate_disc(SNAPSHOT, "disc-1", Limits()) == Decimal("0.20")


def test_estimate_follows_the_rate_in_the_limits() -> None:
    limits = Limits(usd_per_minute=Decimal("0.05"))

    assert estimate_disc(SNAPSHOT, "disc-1", limits) == Decimal("0.50")


def test_unknown_disc_has_no_estimate() -> None:
    assert estimate_disc(SNAPSHOT, "disc-9", Limits()) is None


def test_disc_without_duration_has_no_estimate() -> None:
    assert estimate_disc(SNAPSHOT, "disc-empty", Limits()) is None
