import pytest

from fareguard.ops.table import LedgerTable, LedgerTableError, ledger_table

# A made-up ARN with the shape of a real one; the account is twelve zeros.
OUTPUTS = {
    "ledger_table_name": "fareguard-dev-ledger",
    "ledger_table_arn": "arn:aws:dynamodb:eu-west-1:000000000000:table/fareguard-dev-ledger",
}


def test_the_table_has_the_name_of_the_output_and_the_region_of_its_arn() -> None:
    assert ledger_table(OUTPUTS) == LedgerTable("fareguard-dev-ledger", "eu-west-1")


@pytest.mark.parametrize("missing", sorted(OUTPUTS))
def test_a_missing_output_is_named_in_the_error(missing: str) -> None:
    outputs = {name: value for name, value in OUTPUTS.items() if name != missing}

    with pytest.raises(LedgerTableError, match=missing):
        ledger_table(outputs)


@pytest.mark.parametrize("name", ["", 7, None])
def test_a_name_that_is_not_text_is_refused(name: object) -> None:
    with pytest.raises(LedgerTableError, match="ledger_table_name"):
        ledger_table({**OUTPUTS, "ledger_table_name": name})


@pytest.mark.parametrize("arn", ["not-an-arn", "arn:aws:dynamodb::000000000000:table/t", 7])
def test_an_arn_without_a_region_is_refused(arn: object) -> None:
    with pytest.raises(LedgerTableError, match="ledger_table_arn"):
        ledger_table({**OUTPUTS, "ledger_table_arn": arn})


def test_the_error_does_not_repeat_the_value_of_the_output() -> None:
    with pytest.raises(LedgerTableError) as raised:
        ledger_table({**OUTPUTS, "ledger_table_arn": "odd-value"})

    assert "odd-value" not in str(raised.value)
