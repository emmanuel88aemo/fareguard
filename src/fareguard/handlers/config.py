"""The configuration of the Lambda functions, read from environment variables.

Every variable is required. A missing or invalid value is an error: there is
no default, because a guessed cap is a cap nobody set.

The ledger and the limits are read by both functions. The guardrail is read by
the hook function only, with `load_guardrail_config`; the tools function never
needs it.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from fareguard.gate.models import Limits

TABLE_NAME = "FAREGUARD_TABLE_NAME"
MAX_USD_PER_DISC = "FAREGUARD_MAX_USD_PER_DISC"
MONTHLY_CAP_USD = "FAREGUARD_MONTHLY_CAP_USD"
USD_PER_MINUTE = "FAREGUARD_USD_PER_MINUTE"
GUARDRAIL_ID = "FAREGUARD_GUARDRAIL_ID"
GUARDRAIL_VERSION = "FAREGUARD_GUARDRAIL_VERSION"

_TABLE_NAME_SHAPE = "3 to 255 characters from a-z, A-Z, 0-9, '_', '-' and '.'"
_TABLE_NAME = re.compile(r"[a-zA-Z0-9_.-]{3,255}")
# Plain notation only, with ASCII digits: no sign, no exponent, no NaN and no Infinity.
_AMOUNT_SHAPE = "an amount of USD in plain notation, such as 1.00"
_AMOUNT = re.compile(r"[0-9]{1,9}(\.[0-9]{1,6})?")
_ZERO = Decimal("0")
# The id alone, never the ARN of the guardrail: an ARN holds an account id.
_GUARDRAIL_ID_SHAPE = "the id of a guardrail: 1 to 64 characters from a-z and 0-9"
_GUARDRAIL_ID = re.compile(r"[a-z0-9]{1,64}")
# A published version only. The working draft can change under a running function.
_GUARDRAIL_VERSION_SHAPE = "a published guardrail version: a number from 1 to 99999999"
_GUARDRAIL_VERSION = re.compile(r"[1-9][0-9]{0,7}")


class ConfigError(Exception):
    """An environment variable is missing or does not hold a usable value."""

    def __init__(self, variable: str, expected: str) -> None:
        """Name the variable and what it must hold, without repeating its value."""
        super().__init__(f"the environment variable {variable} must be set to {expected}")


@dataclass(frozen=True)
class Config:
    """What a Lambda function needs to know: the ledger table and the limits."""

    table_name: str
    limits: Limits


@dataclass(frozen=True)
class GuardrailConfig:
    """The guardrail the hook applies: its id and one published version of it."""

    guardrail_id: str
    guardrail_version: str


def load_guardrail_config(environ: Mapping[str, str]) -> GuardrailConfig:
    """Return the guardrail named in `environ`.

    Raises:
        ConfigError: if a variable is missing or its value is invalid.
    """
    return GuardrailConfig(
        guardrail_id=_read_matching(environ, GUARDRAIL_ID, _GUARDRAIL_ID, _GUARDRAIL_ID_SHAPE),
        guardrail_version=_read_matching(
            environ, GUARDRAIL_VERSION, _GUARDRAIL_VERSION, _GUARDRAIL_VERSION_SHAPE
        ),
    )


def _read_matching(
    environ: Mapping[str, str], variable: str, shape: re.Pattern[str], expected: str
) -> str:
    value = environ.get(variable)
    if value is None or shape.fullmatch(value) is None:
        raise ConfigError(variable, expected)
    return value


def load_config(environ: Mapping[str, str]) -> Config:
    """Return the configuration held in `environ`.

    The caps may be zero, which denies every launch. The rate must be greater
    than zero, because no cost can be estimated without one.

    Raises:
        ConfigError: if a variable is missing or its value is invalid.
    """
    return Config(
        table_name=_read_table_name(environ),
        limits=Limits(
            max_usd_per_disc=_read_amount(environ, MAX_USD_PER_DISC),
            monthly_cap_usd=_read_amount(environ, MONTHLY_CAP_USD),
            usd_per_minute=_read_rate(environ),
        ),
    )


def _read_table_name(environ: Mapping[str, str]) -> str:
    value = environ.get(TABLE_NAME)
    if value is None or _TABLE_NAME.fullmatch(value) is None:
        raise ConfigError(TABLE_NAME, _TABLE_NAME_SHAPE)
    return value


def _read_amount(environ: Mapping[str, str], variable: str) -> Decimal:
    value = environ.get(variable)
    if value is None or _AMOUNT.fullmatch(value) is None:
        raise ConfigError(variable, _AMOUNT_SHAPE)
    return Decimal(value)


def _read_rate(environ: Mapping[str, str]) -> Decimal:
    rate = _read_amount(environ, USD_PER_MINUTE)
    if rate <= _ZERO:
        raise ConfigError(USD_PER_MINUTE, f"{_AMOUNT_SHAPE}, greater than 0")
    return rate
