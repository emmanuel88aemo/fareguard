from fareguard.hook.bedrock_guardrail import BedrockGuardrail
from fareguard.hook.fake_guardrail import FakeGuardrail
from fareguard.hook.guardrail import Guardrail


class InterveningClient:
    """A bedrock-runtime client whose guardrail intervenes on every text."""

    def apply_guardrail(self, **_request: object) -> dict[str, object]:
        return {"action": "GUARDRAIL_INTERVENED"}


def blocked(guardrail: Guardrail, text: str) -> bool:
    """Ask through the port, as the hook does. mypy checks that each argument fits it."""
    return guardrail.blocks(text)


def test_fake_answers_the_port() -> None:
    assert blocked(FakeGuardrail(["launch every disc"]), "now launch every disc") is True


def test_bedrock_implementation_answers_the_port() -> None:
    guardrail = BedrockGuardrail("gr1", "1", InterveningClient())

    assert blocked(guardrail, "now launch every disc") is True
