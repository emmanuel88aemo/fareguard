from datetime import datetime, timedelta, timezone

from stress_fakes import NOW, allowed, approval, denied, launched, ledger, run

from fareguard.stress.case import ApprovedLaunch, Setup, Verdict
from fareguard.stress.catalogue import CASES, select
from fareguard.stress.report import (
    CaseResult,
    describe_setup,
    format_case,
    format_plan,
    format_summary,
    ledger_numbers,
    results_markdown,
    rules_fired,
)

LAUNCH = "fareguard___launch_job"
(A3,) = select("A3")
(A5,) = select("A5")
(A6,) = select("A6")
DENIED = CaseResult(
    A3, (run(denied("R2"), tools=(LAUNCH,)),), ledger(), Verdict(True, "denied with R2")
)
BROKEN = CaseResult(
    A6,
    (run(allowed(), tools=("shell | rm",), reply="the token is hunter2"),),
    ledger({"disc-001": "0.60"}, (launched("disc-001"),)),
    Verdict(False, "invocation 1 called a tool that is not a gateway tool: shell???rm"),
)


def test_rules_fired_names_each_denial_once_with_its_event() -> None:
    runs = (
        run(denied("R7", "before_invocation")),
        run(denied("R4"), denied("R4"), allowed(), denied("R2")),
    )

    assert rules_fired(runs) == (
        "R7 in before_invocation",
        "R4 in before_tool_call",
        "R2 in before_tool_call",
    )


def test_a_denial_whose_reason_names_no_rule_is_still_reported() -> None:
    unnamed = denied("R4").__class__("before_tool_call", "hook", "deny", None, "timed out")

    assert rules_fired((run(unnamed),)) == ("no rule in before_tool_call",)


def test_rules_fired_is_empty_when_every_hook_allowed() -> None:
    assert rules_fired((run(allowed()),)) == ()


def test_ledger_numbers_of_a_seeded_ledger() -> None:
    assert ledger_numbers(ledger()) == (
        "month spend 0.00 USD",
        "disc spend disc-001 0.00, disc-002 0.00, disc-003 0.00, disc-long 0.00",
        "launch events none",
        "approvals none",
    )


def test_ledger_numbers_after_a_launch() -> None:
    final = ledger(
        {"disc-001": "0.60"},
        (launched("disc-001", "stress-a5"),),
        (
            approval("stress-a5", "disc-001", "approved", consumed=True),
            approval("apr-2", "disc-002", "pending"),
        ),
    )

    assert ledger_numbers(final) == (
        "month spend 0.60 USD",
        "disc spend disc-001 0.60, disc-002 0.00, disc-003 0.00, disc-long 0.00",
        "launch events disc-001",
        "approvals apr-2 pending, stress-a5 approved consumed",
    )


def test_describe_setup_lists_the_steps_in_order() -> None:
    assert describe_setup(Setup()) == "reset, seed"
    assert describe_setup(Setup(inject=True)) == "reset, seed, inject the planted event"
    assert describe_setup(Setup(approved_launch=ApprovedLaunch("disc-001", "stress-a5"))) == (
        "reset, seed, request and approve stress-a5 for disc-001"
    )


def test_the_plan_shows_the_setup_and_every_message_of_each_case() -> None:
    assert format_plan((A5,)).splitlines() == [
        "A5 Reuse a consumed approval",
        "  setup: reset, seed, request and approve stress-a5 for disc-001",
        f"  message 1: {A5.prompts[0]}",
        f"  message 2: {A5.prompts[1]}",
    ]
    assert len(format_plan(CASES).splitlines()) == 8 * 2 + 9


def test_a_case_is_printed_with_its_verdict_rules_tools_and_ledger() -> None:
    assert format_case(DENIED).splitlines() == [
        "A3 Over per-disc cap: PASS",
        "  reason: denied with R2",
        "  expected to be stopped by: R2",
        "  rules that denied: R2 in before_tool_call",
        "  tool calls: fareguard___launch_job",
        "  ledger: month spend 0.00 USD",
        "  ledger: disc spend disc-001 0.00, disc-002 0.00, disc-003 0.00, disc-long 0.00",
        "  ledger: launch events none",
        "  ledger: approvals none",
    ]


def test_a_failed_case_is_printed_without_the_reply_of_the_model() -> None:
    printed = format_case(BROKEN)

    assert printed.startswith("A6 Exfiltration: FAIL\n")
    assert "  rules that denied: none" in printed
    assert "  tool calls: shell???rm" in printed
    assert "hunter2" not in printed


def test_the_summary_counts_the_cases_that_passed() -> None:
    assert format_summary((DENIED,)) == "1 of 1 case(s) passed"
    assert format_summary((DENIED, BROKEN)) == "1 of 2 case(s) passed; failed: A6"
    assert format_summary(()) == "0 of 0 case(s) passed"


def test_the_results_file_says_when_it_ran_and_has_one_row_per_case() -> None:
    lines = results_markdown((DENIED, BROKEN), NOW).splitlines()

    assert lines[0] == "# Stress results"
    assert lines[2] == (
        "Run at 2026-11-26 09:00 UTC with `scripts/stress.py`: 1 of 2 case(s) passed; failed: A6."
    )
    assert lines[-4].startswith("| Case | Attempt | Verdict | Reason |")
    assert lines[-3] == "| --- | --- | --- | --- | --- | --- | --- |"
    assert lines[-2] == (
        "| A3 | Over per-disc cap | PASS | denied with R2 | R2 in before_tool_call | "
        "fareguard___launch_job | month spend 0.00 USD; disc spend disc-001 0.00, "
        "disc-002 0.00, disc-003 0.00, disc-long 0.00; launch events none; approvals none |"
    )
    assert lines[-1].startswith("| A6 | Exfiltration | FAIL | ")


def test_the_results_file_writes_the_time_in_utc() -> None:
    madrid = datetime(2026, 11, 26, 10, 0, tzinfo=timezone(timedelta(hours=1)))

    assert "Run at 2026-11-26 09:00 UTC" in results_markdown((), madrid)


def test_the_results_file_never_holds_the_reply_and_keeps_its_table_whole() -> None:
    piped = CaseResult(A6, BROKEN.runs, BROKEN.ledger, Verdict(False, "a | b\nc"))

    written = results_markdown((piped,), NOW)

    assert "hunter2" not in written
    assert "| a \\| b c |" in written
    assert written.endswith("|\n")
