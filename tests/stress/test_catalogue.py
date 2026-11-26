import pytest
from stress_fakes import NOW

from fareguard.gate.validation import is_identifier
from fareguard.harness.run import build_request
from fareguard.ops.seed_data import PLANTED_INSTRUCTION, SEED_DISCS, planted_event
from fareguard.stress import verdicts
from fareguard.stress.case import ApprovedLaunch
from fareguard.stress.catalogue import CASES, UnknownCaseError, select

SESSION = "session-0123456789012345678901234567890"
SEEDED = {disc.disc_id for disc in SEED_DISCS}


def test_the_cases_are_a1_to_a8_in_order() -> None:
    assert [case.case_id for case in CASES] == [f"A{number}" for number in range(1, 9)]


def test_every_case_has_a_title_and_names_the_rules_that_stop_it() -> None:
    assert all(case.title and case.stopped_by for case in CASES)


def test_every_prompt_can_be_sent_to_the_harness() -> None:
    for case in CASES:
        for prompt in case.prompts:
            assert build_request("arn", SESSION, prompt)["messages"]


def test_only_a5_sends_two_messages() -> None:
    assert {case.case_id: len(case.prompts) for case in CASES if len(case.prompts) != 1} == {
        "A5": 2
    }


def test_only_a2_plants_the_event() -> None:
    assert [case.case_id for case in CASES if case.setup.inject] == ["A2"]


def test_the_planted_event_names_the_disc_a2_watches() -> None:
    assert planted_event(NOW).detail["disc_id"] == verdicts.PLANTED_DISC_ID
    assert verdicts.PLANTED_DISC_ID in PLANTED_INSTRUCTION


def test_a3_and_a5_start_with_an_approval_for_the_disc_they_launch() -> None:
    approved = {
        case.case_id: case.setup.approved_launch.disc_id
        for case in CASES
        if case.setup.approved_launch is not None
    }

    assert approved == {"A3": "disc-long", "A5": "disc-001"}


def test_an_approved_launch_names_a_seeded_disc_and_its_ref_is_in_every_prompt() -> None:
    for case in CASES:
        launch = case.setup.approved_launch
        if launch is not None:
            assert launch.disc_id in SEEDED
            assert is_identifier(launch.ref)
            assert launch.disc_id in case.prompts[0]
            assert all(launch.ref in prompt for prompt in case.prompts)


def test_a5_reuses_its_ref_on_another_seeded_disc() -> None:
    (a5,) = select("A5")

    assert verdicts.REUSE_DISC_ID in SEEDED
    assert a5.setup.approved_launch == ApprovedLaunch(verdicts.HAPPY_DISC_ID, "stress-a5")
    assert verdicts.REUSE_DISC_ID in a5.prompts[1]
    assert verdicts.HAPPY_DISC_ID not in a5.prompts[1]


def test_all_selects_every_case() -> None:
    assert select("all") == CASES
    assert select(" ALL ") == CASES


@pytest.mark.parametrize("asked", ["A5", "a5", " a5 "])
def test_one_case_is_selected_by_its_id_in_any_case(asked: str) -> None:
    assert [case.case_id for case in select(asked)] == ["A5"]


@pytest.mark.parametrize("asked", ["A9", "", "A", "A1 A2", "Ignore the rules"])
def test_an_unknown_case_is_refused_without_being_repeated(asked: str) -> None:
    with pytest.raises(UnknownCaseError) as refused:
        select(asked)

    assert str(refused.value) == "the case must be one of A1, A2, A3, A4, A5, A6, A7, A8 or all"
