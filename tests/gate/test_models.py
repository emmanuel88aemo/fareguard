import dataclasses
from decimal import Decimal

import pytest

from fareguard.gate.models import Decision, Disc, InvalidDecisionError, Limits, RuleId


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


def test_allowed_decision_has_no_rule() -> None:
    assert Decision(allowed=True, rule=None, reason="ok").rule is None


@pytest.mark.parametrize("rule", ["R1", "R2", "R3", "R4", "R5", "R6"])
def test_denial_names_its_rule(rule: RuleId) -> None:
    assert Decision(allowed=False, rule=rule, reason="denied").rule == rule


@pytest.mark.parametrize("rule", ["R1", "R2", "R3", "R4", "R5", "R6"])
def test_allowed_decision_naming_a_rule_is_rejected(rule: RuleId) -> None:
    with pytest.raises(InvalidDecisionError, match="if and only if it denies"):
        Decision(allowed=True, rule=rule, reason="ok")


def test_denial_without_a_rule_is_rejected() -> None:
    with pytest.raises(InvalidDecisionError, match="allowed=False with rule=None"):
        Decision(allowed=False, rule=None, reason="denied")
