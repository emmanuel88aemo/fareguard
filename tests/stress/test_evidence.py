from decimal import Decimal

from stress_fakes import NOW, allowed, approval, denied, launched, ledger, run

from fareguard.ledger.store import LedgerEvent
from fareguard.stress.evidence import (
    GATEWAY_TOOLS,
    approved_refs,
    calls_tool,
    denials,
    disc_spend,
    foreign_tool_calls,
    launch_events,
    shown,
    spent_discs,
    tool_names,
)


def test_the_gateway_tools_are_the_four_of_the_harness() -> None:
    assert frozenset({"read_ledger", "list_pending", "request_approval", "launch_job"}) == (
        GATEWAY_TOOLS
    )


def test_a_tool_name_is_shown_as_it_is_when_it_is_plain() -> None:
    assert shown("fareguard___launch_job") == "fareguard___launch_job"


def test_a_tool_name_is_cut_and_stripped_of_other_characters() -> None:
    assert shown("rm -rf /|\n`x`") == "rm?-rf?????x?"
    assert shown("a" * 200) == "a" * 64
    assert shown("") == "?"


def test_tool_names_lists_every_call_of_every_run_in_order() -> None:
    runs = [run(tools=("fareguard___read_ledger",)), run(tools=("shell", "fareguard___launch_job"))]

    assert tool_names(runs) == ("fareguard___read_ledger", "shell", "fareguard___launch_job")


def test_a_gateway_tool_is_not_foreign_with_or_without_its_target() -> None:
    names = ("fareguard___read_ledger", "list_pending", "fareguard___request_approval")

    assert foreign_tool_calls(run(tools=names)) == ()


def test_any_other_tool_is_foreign() -> None:
    names = ("shell", "fareguard___launch_job", "fareguard___approve", "read ledger")

    assert foreign_tool_calls(run(tools=names)) == ("shell", "fareguard___approve", "read?ledger")


def test_calls_tool_compares_the_name_without_the_target() -> None:
    called = run(tools=("fareguard___launch_job",))

    assert calls_tool(called, "launch_job")
    assert not calls_tool(called, "read_ledger")
    assert not calls_tool(run(), "launch_job")


def test_denials_counts_the_before_tool_call_denials_of_one_rule() -> None:
    answered = run(denied("R4"), denied("R4"), denied("R2"), allowed())

    assert denials(answered, "R4") == 2
    assert denials(answered, "R2") == 1
    assert denials(answered, "R1") == 0


def test_a_denial_of_another_event_is_not_a_denied_tool_call() -> None:
    assert (
        denials(run(denied("R7", "before_invocation"), denied("R7", "after_tool_call")), "R7") == 0
    )


def test_launch_events_leaves_out_every_other_event() -> None:
    note = LedgerEvent(NOW, "operator_note:seed", "operator_note", {"disc_id": "disc-003"})
    launch = launched("disc-001")

    assert launch_events(ledger(events=(note, launch))) == (launch,)


def test_launch_events_of_one_disc_leaves_out_the_other_discs() -> None:
    first, second = launched("disc-001", "apr-1"), launched("disc-002", "apr-2")
    final = ledger(events=(first, second))

    assert launch_events(final, "disc-002") == (second,)
    assert launch_events(final, "disc-003") == ()


def test_a_launch_event_that_names_no_disc_counts_for_every_disc() -> None:
    unnamed = LedgerEvent(NOW, "job_launched:apr-9", "job_launched", {})

    assert launch_events(ledger(events=(unnamed,)), "disc-003") == (unnamed,)


def test_disc_spend_is_zero_for_a_disc_with_no_entry() -> None:
    final = ledger({"disc-001": "0.60"})

    assert disc_spend(final, "disc-001") == Decimal("0.60")
    assert disc_spend(final, "disc-long") == Decimal("0.00")


def test_spent_discs_names_only_the_discs_with_spend() -> None:
    final = ledger({"disc-002": "0.60", "disc-001": "0.20", "disc-003": "0.00"})

    assert spent_discs(final) == ("disc-001", "disc-002")
    assert spent_discs(ledger()) == ()


def test_approved_refs_leaves_out_pending_and_rejected_approvals() -> None:
    approvals = (
        approval("apr-3", "disc-003", "approved", consumed=True),
        approval("apr-1", "disc-001", "approved"),
        approval("apr-2", "disc-002", "pending"),
        approval("apr-4", "disc-long", "rejected"),
    )

    assert approved_refs(ledger(approvals=approvals)) == ("apr-1", "apr-3")
