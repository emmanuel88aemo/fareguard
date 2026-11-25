from decimal import Decimal

import pytest

from fareguard.gate.pricing import (
    InvalidDurationError,
    InvalidRateError,
    PricingError,
    estimate_cost,
)

RATE = Decimal("0.02")


@pytest.mark.parametrize(
    ("duration_seconds", "expected"),
    [
        pytest.param(1, "0.02", id="one-second-bills-a-full-minute"),
        pytest.param(59, "0.02", id="under-a-minute-bills-one-minute"),
        pytest.param(60, "0.02", id="exact-minute-bills-one-minute"),
        pytest.param(61, "0.04", id="one-second-over-bills-the-next-minute"),
        pytest.param(3000, "1.00", id="fifty-minutes"),
        pytest.param(4500, "1.50", id="seventy-five-minutes"),
    ],
)
def test_every_started_minute_is_billed(duration_seconds: int, expected: str) -> None:
    assert estimate_cost(duration_seconds, RATE) == Decimal(expected)


@pytest.mark.parametrize(
    ("duration_seconds", "rate", "expected"),
    [
        pytest.param(60, "0.021", "0.03", id="fraction-of-a-cent-rounds-up"),
        pytest.param(180, "0.0033", "0.01", id="just-under-a-cent-rounds-up"),
        pytest.param(60, "0.0001", "0.01", id="tiny-cost-is-never-free"),
        pytest.param(120, "0.025", "0.05", id="whole-cents-stay-unchanged"),
    ],
)
def test_cost_is_rounded_up_to_whole_cents(duration_seconds: int, rate: str, expected: str) -> None:
    assert estimate_cost(duration_seconds, Decimal(rate)) == Decimal(expected)


def test_cost_is_a_decimal_with_two_places() -> None:
    cost = estimate_cost(90, RATE)

    assert isinstance(cost, Decimal)
    assert cost.as_tuple().exponent == -2


@pytest.mark.parametrize(
    "duration_seconds",
    [
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param(-3600, id="negative-hour"),
    ],
)
def test_zero_or_negative_duration_is_rejected(duration_seconds: int) -> None:
    with pytest.raises(InvalidDurationError, match="duration must be greater than 0"):
        estimate_cost(duration_seconds, RATE)


@pytest.mark.parametrize(
    "rate",
    [
        pytest.param("0", id="zero"),
        pytest.param("-0.02", id="negative"),
        pytest.param("NaN", id="nan"),
        pytest.param("Infinity", id="infinite"),
    ],
)
def test_unusable_rate_is_rejected(rate: str) -> None:
    with pytest.raises(InvalidRateError, match="rate must be a positive amount"):
        estimate_cost(60, Decimal(rate))


def test_pricing_errors_share_one_base_class() -> None:
    assert issubclass(InvalidDurationError, PricingError)
    assert issubclass(InvalidRateError, PricingError)
