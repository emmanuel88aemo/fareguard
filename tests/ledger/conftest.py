"""Fixtures shared by the ledger tests: one seeded store per implementation."""

from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal

import pytest

from fareguard.gate.models import Approval, Disc
from fareguard.ledger.memory import InMemoryLedgerStore
from fareguard.ledger.store import LedgerStore


def _make_memory_store(
    discs: Iterable[Disc] = (),
    approvals: Iterable[Approval] = (),
    disc_spend_usd: Mapping[str, Decimal] | None = None,
    month_spend_usd: Mapping[str, Decimal] | None = None,
) -> LedgerStore:
    return InMemoryLedgerStore(discs, approvals, disc_spend_usd, month_spend_usd)


@pytest.fixture(params=["memory"])
def make_store(request: pytest.FixtureRequest) -> Callable[..., LedgerStore]:
    """Return a factory that builds a seeded store; the contract suite runs once per param."""
    factories: dict[str, Callable[..., LedgerStore]] = {"memory": _make_memory_store}
    return factories[request.param]
