import dataclasses
from decimal import Decimal

import pytest

from fareguard.gate.models import Decision, Disc, Limits


def test_default_limits_match_the_published_caps() -> None:
    limits = Limits()

    assert limits.max_usd_per_disc == Decimal("1.00")
    assert limits.monthly_cap_usd == Decimal("5.00")
    assert limits.usd_per_minute == Decimal("0.02")


def test_models_cannot_be_modified_after_creation() -> None:
    disc = Disc(disc_id="disc-1", duration_seconds=600)

    with pytest.raises(dataclasses.FrozenInstanceError):
        disc.duration_seconds = 1  # type: ignore[misc]  # the write is the behaviour under test


def test_equal_decisions_compare_equal() -> None:
    assert Decision(True, None, "ok") == Decision(allowed=True, rule=None, reason="ok")
