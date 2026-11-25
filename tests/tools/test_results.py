import json
from decimal import Decimal
from typing import get_args

import pytest

from fareguard.gate.models import RuleId
from fareguard.hook.decide import DENIAL_REASONS
from fareguard.tools.results import Detailed, reason_for, refusal, usd

RULES: tuple[RuleId, ...] = get_args(RuleId.__value__)


@pytest.mark.parametrize("rule", RULES)
def test_refusal_names_its_rule_with_the_fixed_sentence_of_the_hook(rule: RuleId) -> None:
    assert refusal(rule) == {"refused": True, "rule": rule, "reason": DENIAL_REASONS[rule]}
    assert reason_for(rule).startswith(f"{rule}: ")


def test_refusal_is_json_serialisable() -> None:
    assert json.loads(json.dumps(refusal("R5")))["rule"] == "R5"


@pytest.mark.parametrize(
    ("amount", "text"),
    [
        (Decimal("0.2"), "0.20"),
        (Decimal("5"), "5.00"),
        (Decimal("0.00"), "0.00"),
        (Decimal("1E+1"), "10.00"),
        (Decimal("4.999"), "4.99"),
    ],
)
def test_usd_is_a_string_with_two_decimals(amount: Decimal, text: str) -> None:
    assert usd(amount) == text


def test_detail_is_kept_beside_the_result_not_in_it() -> None:
    detailed = Detailed(refusal("R4"), "no approval with ref 'apr-9' exists")

    assert detailed.result == refusal("R4")
    assert "apr-9" not in json.dumps(detailed.result)
