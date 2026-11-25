"""Cost estimate for processing one disc."""

from decimal import ROUND_CEILING, Decimal

_SECONDS_PER_MINUTE = 60
_ONE_CENT = Decimal("0.01")


class PricingError(ValueError):
    """The inputs cannot produce a trustworthy cost estimate."""


class InvalidDurationError(PricingError):
    """The duration is zero or negative."""

    def __init__(self, duration_seconds: int) -> None:
        """Record the rejected duration."""
        super().__init__(f"duration must be greater than 0 seconds, got {duration_seconds}")


class InvalidRateError(PricingError):
    """The rate is zero, negative or not a finite number."""

    def __init__(self, usd_per_minute: Decimal) -> None:
        """Record the rejected rate."""
        super().__init__(f"rate must be a positive amount of USD, got {usd_per_minute}")


def estimate_cost(duration_seconds: int, usd_per_minute: Decimal) -> Decimal:
    """Return the cost in USD of processing `duration_seconds` of video.

    Every started minute is billed in full and the result is rounded up to
    whole cents, so the estimate is never below the real cost.

    Raises:
        InvalidDurationError: if the duration is zero or negative.
        InvalidRateError: if the rate is zero, negative, NaN or infinite.
    """
    if duration_seconds <= 0:
        raise InvalidDurationError(duration_seconds)
    if not usd_per_minute.is_finite() or usd_per_minute <= 0:
        raise InvalidRateError(usd_per_minute)
    started_minutes = -(-duration_seconds // _SECONDS_PER_MINUTE)
    return (started_minutes * usd_per_minute).quantize(_ONE_CENT, rounding=ROUND_CEILING)
