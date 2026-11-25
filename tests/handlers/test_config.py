from decimal import Decimal

import pytest

from fareguard.gate.models import Limits
from fareguard.gate.validation import are_well_formed_limits
from fareguard.handlers.config import (
    GUARDRAIL_ID,
    GUARDRAIL_VERSION,
    MAX_USD_PER_DISC,
    MONTHLY_CAP_USD,
    TABLE_NAME,
    USD_PER_MINUTE,
    Config,
    ConfigError,
    GuardrailConfig,
    load_config,
    load_guardrail_config,
)

ENVIRON = {
    TABLE_NAME: "fareguard-dev-ledger",
    MAX_USD_PER_DISC: "1.00",
    MONTHLY_CAP_USD: "5.00",
    USD_PER_MINUTE: "0.02",
}
AMOUNTS = (MAX_USD_PER_DISC, MONTHLY_CAP_USD, USD_PER_MINUTE)
MARKER = "not-a-number-7f3a"


def test_variables_follow_the_naming_convention() -> None:
    assert set(ENVIRON) == {
        "FAREGUARD_TABLE_NAME",
        "FAREGUARD_MAX_USD_PER_DISC",
        "FAREGUARD_MONTHLY_CAP_USD",
        "FAREGUARD_USD_PER_MINUTE",
    }


def test_complete_environment_is_read() -> None:
    config = load_config(ENVIRON)

    assert config == Config(
        table_name="fareguard-dev-ledger",
        limits=Limits(
            max_usd_per_disc=Decimal("1.00"),
            monthly_cap_usd=Decimal("5.00"),
            usd_per_minute=Decimal("0.02"),
        ),
    )
    assert are_well_formed_limits(config.limits)


def test_amounts_are_read_as_decimal_without_rounding() -> None:
    config = load_config({**ENVIRON, MAX_USD_PER_DISC: "0.10", USD_PER_MINUTE: "0.015"})

    assert str(config.limits.max_usd_per_disc) == "0.10"
    assert str(config.limits.usd_per_minute) == "0.015"


def test_other_variables_are_ignored() -> None:
    assert load_config({**ENVIRON, "AWS_REGION": "us-east-1"}) == load_config(ENVIRON)


@pytest.mark.parametrize("variable", sorted(ENVIRON))
def test_missing_variable_is_an_error_that_names_it(variable: str) -> None:
    environ = {name: value for name, value in ENVIRON.items() if name != variable}

    with pytest.raises(ConfigError, match=variable):
        load_config(environ)


def test_empty_environment_is_an_error() -> None:
    with pytest.raises(ConfigError):
        load_config({})


@pytest.mark.parametrize("variable", AMOUNTS)
@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "abc",
        "-1.00",
        "+1.00",
        "1e2",
        "NaN",
        "Infinity",
        "1,00",
        "1.",
        ".5",
        " 1.00",
        "1.00\n",
        "1.00 USD",
        "$1.00",
        "0x10",
        "1_000",
        "\u0661.\u0660\u0660",  # digits that are not ASCII
        "1" * 10,
        "0.0000001",
    ],
)
def test_invalid_amount_is_an_error(variable: str, value: str) -> None:
    with pytest.raises(ConfigError, match=variable):
        load_config({**ENVIRON, variable: value})


@pytest.mark.parametrize("value", ["0", "0.00"])
def test_rate_of_zero_is_an_error(value: str) -> None:
    with pytest.raises(ConfigError, match=USD_PER_MINUTE):
        load_config({**ENVIRON, USD_PER_MINUTE: value})


@pytest.mark.parametrize("variable", [MAX_USD_PER_DISC, MONTHLY_CAP_USD])
def test_cap_of_zero_is_accepted(variable: str) -> None:
    config = load_config({**ENVIRON, variable: "0"})

    assert are_well_formed_limits(config.limits)


@pytest.mark.parametrize(
    "value", ["", "ab", " fareguard", "fareguard ledger", "fareguard/ledger", "a" * 256, "tablé"]
)
def test_invalid_table_name_is_an_error(value: str) -> None:
    with pytest.raises(ConfigError, match=TABLE_NAME):
        load_config({**ENVIRON, TABLE_NAME: value})


@pytest.mark.parametrize("variable", sorted(ENVIRON))
def test_error_never_repeats_the_invalid_value(variable: str) -> None:
    with pytest.raises(ConfigError) as caught:
        load_config({**ENVIRON, variable: f"{MARKER} !"})

    assert MARKER not in str(caught.value)


GUARDRAIL_ENVIRON = {GUARDRAIL_ID: "gr1abc2def3", GUARDRAIL_VERSION: "3"}


def test_guardrail_variables_follow_the_naming_convention() -> None:
    assert set(GUARDRAIL_ENVIRON) == {"FAREGUARD_GUARDRAIL_ID", "FAREGUARD_GUARDRAIL_VERSION"}


def test_guardrail_is_read() -> None:
    assert load_guardrail_config(GUARDRAIL_ENVIRON) == GuardrailConfig(
        guardrail_id="gr1abc2def3", guardrail_version="3"
    )


def test_guardrail_is_read_without_the_ledger_or_the_limits() -> None:
    assert load_guardrail_config({**ENVIRON, **GUARDRAIL_ENVIRON}) == load_guardrail_config(
        GUARDRAIL_ENVIRON
    )


def test_ledger_and_limits_are_read_without_the_guardrail() -> None:
    # The tools function receives no guardrail variable.
    assert load_config({**ENVIRON, **GUARDRAIL_ENVIRON}) == load_config(ENVIRON)


@pytest.mark.parametrize("variable", sorted(GUARDRAIL_ENVIRON))
def test_missing_guardrail_variable_is_an_error_that_names_it(variable: str) -> None:
    environ = {name: value for name, value in GUARDRAIL_ENVIRON.items() if name != variable}

    with pytest.raises(ConfigError, match=variable):
        load_guardrail_config(environ)


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "GR1ABC",
        "gr1-abc",
        "gr1 abc",
        "gr1abc\n",
        "a" * 65,
        "arn:aws:bedrock:us-east-1:000000000000:guardrail/gr1abc2def3",
        "guardrail/gr1abc2def3",
    ],
)
def test_invalid_guardrail_id_is_an_error(value: str) -> None:
    with pytest.raises(ConfigError, match=GUARDRAIL_ID):
        load_guardrail_config({**GUARDRAIL_ENVIRON, GUARDRAIL_ID: value})


@pytest.mark.parametrize(
    "value",
    ["", " ", "0", "01", "-1", "1.0", "v1", "DRAFT", "draft", "latest", "1\n", " 1", "1" * 9],
)
def test_guardrail_version_that_is_not_a_published_one_is_an_error(value: str) -> None:
    with pytest.raises(ConfigError, match=GUARDRAIL_VERSION):
        load_guardrail_config({**GUARDRAIL_ENVIRON, GUARDRAIL_VERSION: value})


@pytest.mark.parametrize("value", ["1", "3", "12", "99999999"])
def test_published_guardrail_version_is_accepted(value: str) -> None:
    config = load_guardrail_config({**GUARDRAIL_ENVIRON, GUARDRAIL_VERSION: value})

    assert config.guardrail_version == value


@pytest.mark.parametrize("variable", sorted(GUARDRAIL_ENVIRON))
def test_guardrail_error_never_repeats_the_invalid_value(variable: str) -> None:
    with pytest.raises(ConfigError) as caught:
        load_guardrail_config({**GUARDRAIL_ENVIRON, variable: f"{MARKER} !"})

    assert MARKER not in str(caught.value)
