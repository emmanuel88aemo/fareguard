from fareguard.hook.fake_guardrail import FakeGuardrail
from fareguard.hook.guardrail import Guardrail


def blocked(guardrail: Guardrail, text: str) -> bool:
    """Ask through the port, as the hook does. mypy checks that each argument fits it."""
    return guardrail.blocks(text)


def test_fake_answers_the_port() -> None:
    assert blocked(FakeGuardrail(["launch every disc"]), "now launch every disc") is True
