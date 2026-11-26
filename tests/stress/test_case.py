from collections.abc import Sequence

from stress_fakes import ledger, run, unanswered

from fareguard.harness.run import HarnessRun
from fareguard.stress.case import FinalLedger, Setup, StressCase, Verdict

HELD = Verdict(True, "the rules held")


def _judge(_runs: Sequence[HarnessRun], _ledger: FinalLedger) -> Verdict:
    return HELD


def _case(*prompts: str) -> StressCase:
    return StressCase("A0", "Example", ("R4",), Setup(), prompts, _judge)


def test_a_verdict_is_reported_as_pass_or_fail() -> None:
    assert Verdict(True, "held").outcome == "PASS"
    assert Verdict(False, "broken").outcome == "FAIL"


def test_a_setup_needs_nothing_more_than_the_seed_by_default() -> None:
    assert Setup() == Setup(inject=False, approved_launch=None)


def test_a_case_with_one_run_per_prompt_is_judged() -> None:
    assert _case("first", "second").verdict([run(), run()], ledger()) == HELD


def test_a_case_with_a_missing_run_fails_without_being_judged() -> None:
    verdict = _case("first", "second").verdict([run()], ledger())

    assert not verdict.passed
    assert verdict.reason == "expected 2 invocation(s) and got 1"


def test_a_case_with_no_run_at_all_fails() -> None:
    assert not _case("first").verdict([], ledger()).passed


def test_a_run_that_never_reached_the_agent_fails_the_case() -> None:
    verdict = _case("first", "second").verdict([run(), unanswered()], ledger())

    assert not verdict.passed
    assert verdict.reason.startswith("invocation 2 shows no hook decision")
