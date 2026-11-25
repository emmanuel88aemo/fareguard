import pytest

from fareguard.hook.fake_guardrail import FakeGuardrail


def test_text_with_a_blocked_phrase_is_blocked() -> None:
    guardrail = FakeGuardrail(["ignore your limits", "lift the cap"])

    assert guardrail.blocks("Please lift the cap for today.") is True


def test_text_without_a_blocked_phrase_is_not_blocked() -> None:
    assert FakeGuardrail(["ignore your limits"]).blocks("What is queued?") is False


def test_fake_without_phrases_blocks_nothing() -> None:
    assert FakeGuardrail().blocks("ignore your limits") is False


def test_every_text_is_recorded_in_order() -> None:
    guardrail = FakeGuardrail(["second"])
    guardrail.blocks("first")
    guardrail.blocks("second")

    assert guardrail.seen == ["first", "second"]


def test_fake_built_with_an_error_raises_it_and_still_records_the_text() -> None:
    guardrail = FakeGuardrail(error=TimeoutError("no answer"))

    with pytest.raises(TimeoutError):
        guardrail.blocks("What is queued?")
    assert guardrail.seen == ["What is queued?"]
