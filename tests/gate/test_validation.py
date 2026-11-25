import dataclasses
from decimal import Decimal
from typing import Any

import pytest

from fareguard.gate.models import Approval, Disc, LedgerSnapshot, Limits, ToolCall
from fareguard.gate.validation import (
    are_well_formed_limits,
    is_amount,
    is_well_formed_call,
    is_well_formed_snapshot,
)

DISC = Disc(disc_id="disc-1", duration_seconds=600)
APPROVAL = Approval(
    ref="apr-1",
    action="launch_job",
    disc_id="disc-1",
    approved_usd=Decimal("0.20"),
    status="approved",
    consumed=False,
)
SNAPSHOT = LedgerSnapshot(
    discs=(DISC,),
    approvals=(APPROVAL,),
    month_spend_usd=Decimal("1.00"),
    disc_spend_usd={"disc-1": Decimal("0.20")},
)


def snapshot_with(**changes: object) -> LedgerSnapshot:
    """Return the base snapshot with fields replaced, bypassing the type checker."""
    fields: dict[str, Any] = {
        field.name: getattr(SNAPSHOT, field.name) for field in dataclasses.fields(SNAPSHOT)
    }
    return LedgerSnapshot(**{**fields, **changes})


def disc_with(**changes: object) -> Disc:
    fields: dict[str, Any] = {**dataclasses.asdict(DISC), **changes}
    return Disc(**fields)


def approval_with(**changes: object) -> Approval:
    fields: dict[str, Any] = {**dataclasses.asdict(APPROVAL), **changes}
    return Approval(**fields)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(Decimal("0"), id="zero"),
        pytest.param(Decimal("0.01"), id="one-cent"),
        pytest.param(Decimal("5.00"), id="five-dollars"),
    ],
)
def test_finite_non_negative_decimal_is_an_amount(value: object) -> None:
    assert is_amount(value) is True


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(Decimal("-0.01"), id="negative"),
        pytest.param(Decimal("NaN"), id="nan"),
        pytest.param(Decimal("sNaN"), id="signalling-nan"),
        pytest.param(Decimal("Infinity"), id="infinite"),
        pytest.param(0.5, id="float"),
        pytest.param(1, id="int"),
        pytest.param("1.00", id="string"),
        pytest.param(None, id="none"),
    ],
)
def test_anything_else_is_not_an_amount(value: object) -> None:
    assert is_amount(value) is False


def test_tool_call_with_string_name_and_mapping_is_well_formed() -> None:
    assert is_well_formed_call(ToolCall("launch_job", {"disc_id": "disc-1"})) is True


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(None, id="none"),
        pytest.param({"name": "read_ledger", "arguments": {}}, id="dict"),
        pytest.param(ToolCall(None, {}), id="name-is-none"),  # type: ignore[arg-type]  # wrong type under test
        pytest.param(ToolCall("read_ledger", None), id="arguments-is-none"),  # type: ignore[arg-type]  # wrong type under test
        pytest.param(ToolCall("read_ledger", ["a"]), id="arguments-is-a-list"),  # type: ignore[arg-type]  # wrong type under test
    ],
)
def test_call_of_the_wrong_shape_is_not_well_formed(call: object) -> None:
    assert is_well_formed_call(call) is False


@pytest.mark.parametrize(
    "snapshot",
    [
        pytest.param(SNAPSHOT, id="typical"),
        pytest.param(snapshot_with(discs=(), approvals=(), disc_spend_usd={}), id="empty-ledger"),
    ],
)
def test_typed_snapshot_is_well_formed(snapshot: LedgerSnapshot) -> None:
    assert is_well_formed_snapshot(snapshot) is True


@pytest.mark.parametrize(
    "snapshot",
    [
        pytest.param(None, id="none"),
        pytest.param({"discs": ()}, id="dict"),
        pytest.param(snapshot_with(discs=[DISC]), id="discs-is-a-list"),
        pytest.param(snapshot_with(discs=None), id="discs-is-none"),
        pytest.param(snapshot_with(approvals=[APPROVAL]), id="approvals-is-a-list"),
        pytest.param(snapshot_with(discs=({"disc_id": "disc-1"},)), id="disc-is-a-dict"),
        pytest.param(snapshot_with(discs=(disc_with(disc_id=1),)), id="disc-id-is-an-int"),
        pytest.param(
            snapshot_with(discs=(disc_with(duration_seconds=600.0),)), id="duration-is-a-float"
        ),
        pytest.param(
            snapshot_with(discs=(disc_with(duration_seconds=True),)), id="duration-is-a-bool"
        ),
        pytest.param(snapshot_with(discs=(DISC, DISC)), id="duplicate-disc-id"),
        pytest.param(snapshot_with(approvals=("apr-1",)), id="approval-is-a-string"),
        pytest.param(snapshot_with(approvals=(approval_with(ref=None),)), id="ref-is-none"),
        pytest.param(snapshot_with(approvals=(approval_with(status=None),)), id="status-is-none"),
        pytest.param(
            snapshot_with(approvals=(approval_with(consumed="no"),)), id="consumed-is-a-string"
        ),
        pytest.param(
            snapshot_with(approvals=(approval_with(approved_usd=0.2),)), id="approved-is-a-float"
        ),
        pytest.param(
            snapshot_with(approvals=(approval_with(approved_usd=Decimal("-1")),)),
            id="approved-is-negative",
        ),
        pytest.param(snapshot_with(approvals=(APPROVAL, APPROVAL)), id="duplicate-approval-ref"),
        pytest.param(snapshot_with(month_spend_usd=Decimal("NaN")), id="month-spend-is-nan"),
        pytest.param(snapshot_with(month_spend_usd=Decimal("-1")), id="month-spend-is-negative"),
        pytest.param(snapshot_with(month_spend_usd=1.0), id="month-spend-is-a-float"),
        pytest.param(snapshot_with(disc_spend_usd=None), id="disc-spend-is-none"),
        pytest.param(snapshot_with(disc_spend_usd={1: Decimal("0.20")}), id="disc-spend-key-int"),
        pytest.param(snapshot_with(disc_spend_usd={"disc-1": 0.2}), id="disc-spend-is-a-float"),
        pytest.param(
            snapshot_with(disc_spend_usd={"disc-1": Decimal("-0.20")}), id="disc-spend-is-negative"
        ),
    ],
)
def test_snapshot_of_the_wrong_shape_is_not_well_formed(snapshot: object) -> None:
    assert is_well_formed_snapshot(snapshot) is False


def test_non_positive_duration_is_left_to_pricing() -> None:
    assert is_well_formed_snapshot(snapshot_with(discs=(disc_with(duration_seconds=0),))) is True


def test_default_limits_are_well_formed() -> None:
    assert are_well_formed_limits(Limits()) is True


@pytest.mark.parametrize(
    "limits",
    [
        pytest.param(None, id="none"),
        pytest.param({"monthly_cap_usd": Decimal("5.00")}, id="dict"),
        pytest.param(Limits(max_usd_per_disc=Decimal("NaN")), id="disc-cap-is-nan"),
        pytest.param(Limits(max_usd_per_disc=Decimal("-1.00")), id="disc-cap-is-negative"),
        pytest.param(Limits(monthly_cap_usd=Decimal("Infinity")), id="monthly-cap-is-infinite"),
        pytest.param(Limits(monthly_cap_usd=5.0), id="monthly-cap-is-a-float"),  # type: ignore[arg-type]  # wrong type under test
        pytest.param(Limits(usd_per_minute=0.02), id="rate-is-a-float"),  # type: ignore[arg-type]  # wrong type under test
    ],
)
def test_limits_of_the_wrong_shape_are_not_well_formed(limits: object) -> None:
    assert are_well_formed_limits(limits) is False
