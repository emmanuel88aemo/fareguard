from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

import owner
from fareguard.gate.models import Approval, Disc
from fareguard.ledger.memory import InMemoryLedgerStore
from fareguard.ledger.store import LedgerStore
from fareguard.ops.table import LedgerTable

NOW = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
# A made-up ARN with the shape of a real one; the account is twelve zeros.
OUTPUTS: Mapping[str, object] = {
    "ledger_table_name": "fareguard-dev-ledger",
    "ledger_table_arn": "arn:aws:dynamodb:us-east-1:000000000000:table/fareguard-dev-ledger",
}
PENDING = Approval("apr-1", "launch_job", "disc-001", Decimal("0.60"), "pending", False)


class FakeStores:
    """Hands out one in-memory store and records the table it was asked for."""

    def __init__(self, *approvals: Approval) -> None:
        discs = (Disc("disc-001", 1800), Disc("disc-002", 1800))
        self.store = InMemoryLedgerStore(discs, approvals)
        self.tables: list[LedgerTable] = []

    def make(self, table: LedgerTable) -> LedgerStore:
        self.tables.append(table)
        return self.store


def _outputs(_directory: Path) -> Mapping[str, object]:
    return OUTPUTS


def _run(argv: list[str], stores: FakeStores) -> int:
    return owner.main(argv, read_outputs=_outputs, make_store=stores.make, now=lambda: NOW)


def _status_of(stores: FakeStores, ref: str) -> str:
    approvals = stores.store.snapshot(NOW).approvals
    return next(approval.status for approval in approvals if approval.ref == ref)


def test_pending_lists_the_ref_the_disc_and_the_amount(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stores = FakeStores(PENDING)

    code = _run(["pending"], stores)

    assert code == 0
    assert stores.tables == [LedgerTable("fareguard-dev-ledger", "us-east-1")]
    assert capsys.readouterr().out.splitlines() == [
        "ref\tdisc\tamount",
        "apr-1\tdisc-001\t0.60 USD",
    ]


def test_pending_says_so_when_nothing_awaits_a_decision(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = _run(["pending"], FakeStores())

    assert code == 0
    assert capsys.readouterr().out == "no approval request is awaiting a decision\n"


def test_pending_leaves_out_a_request_that_was_decided(
    capsys: pytest.CaptureFixture[str],
) -> None:
    decided = Approval("apr-0", "launch_job", "disc-002", Decimal("0.60"), "approved", False)

    _run(["pending"], FakeStores(PENDING, decided))

    assert "apr-0" not in capsys.readouterr().out


def test_approve_decides_the_request_at_the_time_of_the_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stores = FakeStores(PENDING)

    code = _run(["approve", "apr-1"], stores)

    assert code == 0
    assert capsys.readouterr().out == "approved: approval apr-1 for disc disc-001\n"
    assert _status_of(stores, "apr-1") == "approved"
    decided = stores.store.recent_events(1)[0]
    assert (decided.type, decided.at) == ("approval_decided", NOW)


def test_reject_decides_the_request_as_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    stores = FakeStores(PENDING)

    code = _run(["reject", "apr-1"], stores)

    assert code == 0
    assert capsys.readouterr().out == "rejected: approval apr-1 for disc disc-001\n"
    assert _status_of(stores, "apr-1") == "rejected"


def test_an_approval_is_not_consumed_by_its_decision() -> None:
    stores = FakeStores(PENDING)

    _run(["approve", "apr-1"], stores)

    assert [a.consumed for a in stores.store.snapshot(NOW).approvals] == [False]


@pytest.mark.parametrize("command", ["approve", "reject"])
def test_an_unknown_ref_is_an_error_and_changes_nothing(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    stores = FakeStores(PENDING)

    code = _run([command, "apr-9"], stores)

    assert code == 1
    assert "apr-9" in capsys.readouterr().err
    assert _status_of(stores, "apr-1") == "pending"


def test_a_decision_cannot_be_changed(capsys: pytest.CaptureFixture[str]) -> None:
    stores = FakeStores(PENDING)
    _run(["reject", "apr-1"], stores)

    code = _run(["approve", "apr-1"], stores)

    assert code == 1
    assert "not pending" in capsys.readouterr().err
    assert _status_of(stores, "apr-1") == "rejected"


def test_a_malformed_ref_is_refused_without_being_repeated(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = _run(["approve", "Ignore the rules"], FakeStores(PENDING))

    captured = capsys.readouterr()
    assert code == 1
    assert "ref is malformed" in captured.err
    assert "Ignore" not in captured.err


@pytest.mark.parametrize("missing", sorted(OUTPUTS))
def test_a_missing_output_stops_before_any_store_is_built(
    missing: str, capsys: pytest.CaptureFixture[str]
) -> None:
    stores = FakeStores(PENDING)
    outputs = {name: value for name, value in OUTPUTS.items() if name != missing}

    code = owner.main(["pending"], read_outputs=lambda _directory: outputs, make_store=stores.make)

    assert code == 1
    assert stores.tables == []
    assert missing in capsys.readouterr().err


@pytest.mark.parametrize("argv", [[], ["approve"], ["launch", "apr-1"]])
def test_a_command_that_does_not_exist_or_lacks_its_ref_is_refused(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        _run(argv, FakeStores(PENDING))

    assert stopped.value.code == 2


@pytest.mark.parametrize("argv", [["--help"], ["approve", "--help"], ["reject", "--help"]])
def test_the_help_says_a_person_runs_it_with_an_admin_profile(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        _run(argv, FakeStores())

    printed = " ".join(capsys.readouterr().out.split())
    assert "admin profile" in printed
    assert "the agent has no tool that approves" in printed
