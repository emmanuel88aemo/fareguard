from decimal import Decimal

import pytest
from stress_fakes import NOW

from fareguard.gate.models import Approval
from fareguard.hook.decide import decide
from fareguard.ledger.errors import ApprovalRefExistsError
from fareguard.ledger.memory import InMemoryLedgerStore
from fareguard.ops.seed_data import SEED_DISCS, SEED_LIMITS
from fareguard.stress import setup
from fareguard.stress.case import ApprovedLaunch
from fareguard.stress.catalogue import CASES
from fareguard.stress.evidence import launch_events
from fareguard.stress.setup import (
    NoEstimateError,
    TooManyEventsError,
    approve_launch,
    read_final_ledger,
)
from fareguard.stress.verdicts import REUSE_DISC_ID
from fareguard.tools.launch import launch_job

A3 = next(case.setup.approved_launch for case in CASES if case.case_id == "A3")
A5 = next(case.setup.approved_launch for case in CASES if case.case_id == "A5")


def _seeded() -> InMemoryLedgerStore:
    return InMemoryLedgerStore(SEED_DISCS)


def _hook_rule(store: InMemoryLedgerStore, disc_id: str, ref: str) -> str | None:
    """The rule with which the real hook answers a launch_job call, or None when it allows."""
    event = {
        "event": "before_tool_call",
        "context": {
            "toolName": "fareguard___launch_job",
            "toolInput": {"disc_id": disc_id, "approval_ref": ref},
        },
    }
    return decide(event, store, SEED_LIMITS, NOW).record["rule"]


def test_approve_launch_leaves_an_approved_unconsumed_approval_for_the_estimate() -> None:
    store = _seeded()

    estimate_usd = approve_launch(store, ApprovedLaunch("disc-001", "stress-x"), SEED_LIMITS, NOW)

    assert estimate_usd == Decimal("0.60")
    assert store.snapshot(NOW).approvals == (
        Approval("stress-x", "launch_job", "disc-001", Decimal("0.60"), "approved", False),
    )
    assert store.pending_approvals() == ()


def test_approve_launch_goes_through_the_store_and_leaves_both_events() -> None:
    store = _seeded()

    approve_launch(store, ApprovedLaunch("disc-001", "stress-x"), SEED_LIMITS, NOW)

    assert sorted(event.type for event in store.recent_events(10)) == [
        "approval_decided",
        "approval_requested",
    ]


def test_an_unknown_disc_is_refused_and_nothing_is_written() -> None:
    store = _seeded()

    with pytest.raises(NoEstimateError, match="disc-404"):
        approve_launch(store, ApprovedLaunch("disc-404", "stress-x"), SEED_LIMITS, NOW)

    assert store.snapshot(NOW).approvals == ()
    assert store.recent_events(10) == ()


def test_a_ref_that_is_taken_is_an_error_of_the_store() -> None:
    store = _seeded()
    approve_launch(store, ApprovedLaunch("disc-001", "stress-x"), SEED_LIMITS, NOW)

    with pytest.raises(ApprovalRefExistsError):
        approve_launch(store, ApprovedLaunch("disc-002", "stress-x"), SEED_LIMITS, NOW)


def test_the_approval_of_a3_does_not_get_the_long_disc_past_the_hook() -> None:
    assert A3 is not None
    store = _seeded()

    assert approve_launch(store, A3, SEED_LIMITS, NOW) == Decimal("1.50")

    assert _hook_rule(store, A3.disc_id, A3.ref) == "R2"


def test_the_approval_of_a5_launches_once_and_is_then_denied_with_r4_on_another_disc() -> None:
    assert A5 is not None
    store = _seeded()
    approve_launch(store, A5, SEED_LIMITS, NOW)

    assert _hook_rule(store, A5.disc_id, A5.ref) is None
    assert launch_job(A5.disc_id, A5.ref, store, SEED_LIMITS, NOW)["launched"] is True
    assert _hook_rule(store, REUSE_DISC_ID, A5.ref) == "R4"

    final = read_final_ledger(store, NOW)
    assert len(launch_events(final, A5.disc_id)) == 1
    assert final.snapshot.disc_spend_usd[A5.disc_id] == Decimal("0.60")


def test_a_second_launch_of_the_same_disc_is_stopped_by_its_cap_before_the_approval() -> None:
    # Why A5 reuses the ref on another disc: R2 is reported before R4.
    assert A5 is not None
    store = _seeded()
    approve_launch(store, A5, SEED_LIMITS, NOW)
    launch_job(A5.disc_id, A5.ref, store, SEED_LIMITS, NOW)

    assert _hook_rule(store, A5.disc_id, A5.ref) == "R2"


def test_the_final_ledger_holds_the_snapshot_and_every_event() -> None:
    store = _seeded()
    approve_launch(store, ApprovedLaunch("disc-001", "stress-x"), SEED_LIMITS, NOW)

    final = read_final_ledger(store, NOW)

    assert final.snapshot == store.snapshot(NOW)
    assert final.events == store.recent_events(10)
    assert len(final.events) == 2


def test_the_final_ledger_of_a_seeded_table_has_no_event() -> None:
    assert read_final_ledger(_seeded(), NOW).events == ()


def test_a_ledger_with_more_events_than_were_read_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _seeded()
    approve_launch(store, ApprovedLaunch("disc-001", "stress-x"), SEED_LIMITS, NOW)
    monkeypatch.setattr(setup, "EVENT_LIMIT", 2)

    with pytest.raises(TooManyEventsError, match="2 events or more"):
        read_final_ledger(store, NOW)
