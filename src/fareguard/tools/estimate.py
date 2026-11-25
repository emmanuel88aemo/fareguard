"""The estimated cost of one disc, as a tool computes it before it writes."""

from decimal import Decimal

from fareguard.gate.models import LedgerSnapshot, Limits
from fareguard.gate.pricing import PricingError, estimate_cost


def estimate_disc(snapshot: LedgerSnapshot, disc_id: str, limits: Limits) -> Decimal | None:
    """Return the cost in USD of processing the disc, from its duration in `snapshot`.

    Returns None when the disc is not in the snapshot or no cost can be
    estimated from its duration and the rate. The caller refuses in that case.
    """
    disc = next((disc for disc in snapshot.discs if disc.disc_id == disc_id), None)
    if disc is None:
        return None
    try:
        return estimate_cost(disc.duration_seconds, limits.usd_per_minute)
    except PricingError:
        return None
