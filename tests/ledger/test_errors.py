import pytest

from fareguard.ledger.errors import (
    ApprovalDiscMismatchError,
    ApprovalNotPendingError,
    ApprovalRefExistsError,
    InvalidLaunchResultError,
    InvalidLedgerInputError,
    LedgerDataError,
    LedgerError,
    LedgerTransactionError,
    PendingApprovalExistsError,
    UnknownApprovalError,
    UnknownDiscError,
)


@pytest.mark.parametrize(
    ("error", "fragment"),
    [
        pytest.param(ApprovalRefExistsError("apr-1"), "'apr-1' already exists", id="ref-exists"),
        pytest.param(PendingApprovalExistsError("disc-1"), "'disc-1' already has", id="pending"),
        pytest.param(UnknownDiscError("disc-9"), "'disc-9' is not in the ledger", id="unknown"),
        pytest.param(
            UnknownApprovalError("apr-9"), "approval 'apr-9' is not in the ledger", id="unknown-ref"
        ),
        pytest.param(
            ApprovalNotPendingError("apr-1"),
            "approval 'apr-1' is not pending or is already consumed",
            id="not-pending",
        ),
        pytest.param(
            ApprovalDiscMismatchError("apr-1", "disc-1"),
            "disc 'disc-1' is not marked with approval 'apr-1'",
            id="disc-mismatch",
        ),
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


def test_data_error_names_the_attribute() -> None:
    error = LedgerDataError("spent_usd")

    assert isinstance(error, LedgerError)
    assert "'spent_usd'" in str(error)
