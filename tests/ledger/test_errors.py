import pytest

from fareguard.ledger.errors import (
    ApprovalRefExistsError,
    InvalidLaunchResultError,
    InvalidLedgerInputError,
    LedgerError,
    LedgerTransactionError,
    PendingApprovalExistsError,
    UnknownDiscError,
)


@pytest.mark.parametrize(
    ("error", "fragment"),
    [
        pytest.param(ApprovalRefExistsError("apr-1"), "'apr-1' already exists", id="ref-exists"),
        pytest.param(PendingApprovalExistsError("disc-1"), "'disc-1' already has", id="pending"),
        pytest.param(UnknownDiscError("disc-9"), "'disc-9' is not in the ledger", id="unknown"),
        pytest.param(
            InvalidLedgerInputError("disc_id", "an identifier"),
            "disc_id is malformed; expected an identifier",
            id="invalid-input",
        ),
        pytest.param(
            LedgerTransactionError(["TransactionConflict", "None"]),
            "nothing changed: TransactionConflict, None",
            id="transaction",
        ),
    ],
)
def test_ledger_error_explains_itself(error: LedgerError, fragment: str) -> None:
    assert isinstance(error, LedgerError)
    assert fragment in str(error)


def test_invalid_input_is_also_a_value_error() -> None:
    assert issubclass(InvalidLedgerInputError, ValueError)


def test_invalid_launch_result_error_shows_the_contradiction() -> None:
    assert "launched=True with rule='R2'" in str(InvalidLaunchResultError(True, "R2"))
