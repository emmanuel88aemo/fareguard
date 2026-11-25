import dataclasses
from decimal import Decimal
from typing import Any, cast

import pytest

from fareguard.gate.evaluate import evaluate
from fareguard.gate.models import Approval, Decision, Disc, LedgerSnapshot, Limits, ToolCall

LIMITS = Limits()
# Ten minutes at the default rate of 0.02 USD per minute: an estimate of 0.20 USD.
DISC = Disc(disc_id="disc-1", duration_seconds=600)
OTHER_DISC = Disc(disc_id="disc-2", duration_seconds=600)
APPROVAL = Approval(
    ref="apr-1",
    action="launch_job",
    disc_id="disc-1",
    approved_usd=Decimal("0.20"),
    status="approved",
    consumed=False,
)
SNAPSHOT = LedgerSnapshot(
    discs=(DISC, OTHER_DISC),
    approvals=(APPROVAL,),
    month_spend_usd=Decimal("0.00"),
    disc_spend_usd={},
)
LAUNCH = ToolCall(name="launch_job", arguments={"disc_id": "disc-1", "approval_ref": "apr-1"})


def with_approval(**changes: object) -> LedgerSnapshot:
    """Return the base snapshot with its only approval changed."""
    fields: dict[str, Any] = {**dataclasses.asdict(APPROVAL), **changes}
    return dataclasses.replace(SNAPSHOT, approvals=(Approval(**fields),))


def with_disc(duration_seconds: int, approved_usd: str) -> LedgerSnapshot:
    """Return a snapshot whose disc has the given duration and a matching approval."""
    disc = dataclasses.replace(DISC, duration_seconds=duration_seconds)
    approval = dataclasses.replace(APPROVAL, approved_usd=Decimal(approved_usd))
    return dataclasses.replace(SNAPSHOT, discs=(disc,), approvals=(approval,))


def with_spend(month: str = "0.00", disc: str | None = None) -> LedgerSnapshot:
    """Return the base snapshot with spend already recorded."""
    disc_spend = {} if disc is None else {"disc-1": Decimal(disc)}
    return dataclasses.replace(SNAPSHOT, month_spend_usd=Decimal(month), disc_spend_usd=disc_spend)


def assert_denied(decision: Decision, rule: str) -> None:
    assert decision.allowed is False
    assert decision.rule == rule
    assert decision.reason


def test_approved_launch_within_caps_is_allowed() -> None:
    decision = evaluate(LAUNCH, SNAPSHOT, LIMITS)

    assert decision.allowed is True
    assert decision.rule is None


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(ToolCall("read_ledger", {}), id="read_ledger"),
        pytest.param(ToolCall("list_pending", {}), id="list_pending"),
        pytest.param(ToolCall("request_approval", {"disc_id": "disc-1"}), id="request_approval"),
    ],
)
def test_well_formed_call_to_a_free_tool_is_allowed(call: ToolCall) -> None:
    assert evaluate(call, SNAPSHOT, LIMITS) == Decision(True, None, "allowed")


def test_read_tools_are_allowed_when_the_snapshot_is_unusable() -> None:
    broken = dataclasses.replace(SNAPSHOT, month_spend_usd=Decimal("NaN"))

    assert evaluate(ToolCall("read_ledger", {}), broken, LIMITS).allowed is True


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("delete_ledger", id="invented-tool"),
        pytest.param("approve", id="self-approval-tool"),
        pytest.param("Launch_Job", id="wrong-case"),
        pytest.param("launch_job ", id="trailing-space"),
        pytest.param("", id="empty-name"),
    ],
)
def test_unknown_tool_is_denied_by_r1(name: str) -> None:
    decision = evaluate(ToolCall(name, dict(LAUNCH.arguments)), SNAPSHOT, LIMITS)

    assert_denied(decision, "R1")
    assert repr(name) in decision.reason


@pytest.mark.parametrize(
    ("snapshot", "limits", "numbers"),
    [
        pytest.param(
            with_disc(duration_seconds=4500, approved_usd="1.50"),
            LIMITS,
            ("1.50", "1.00"),
            id="A3-75-minute-disc-estimated-at-1.50",
        ),
        pytest.param(
            dataclasses.replace(
                with_disc(duration_seconds=1500, approved_usd="0.75"),
                disc_spend_usd={"disc-1": Decimal("0.75")},
            ),
            dataclasses.replace(LIMITS, usd_per_minute=Decimal("0.03")),
            ("0.75", "1.50", "1.00"),
            id="A4-split-job-0.75-spent-plus-0.75-estimate",
        ),
        pytest.param(
            with_spend(disc="0.81"),
            LIMITS,
            ("0.81", "0.20", "1.01", "1.00"),
            id="total-of-1.01-is-one-cent-over",
        ),
    ],
)
def test_launch_over_the_disc_cap_is_denied_by_r2(
    snapshot: LedgerSnapshot, limits: Limits, numbers: tuple[str, ...]
) -> None:
    decision = evaluate(LAUNCH, snapshot, limits)

    assert_denied(decision, "R2")
    assert all(number in decision.reason for number in numbers)


@pytest.mark.parametrize(
    "snapshot",
    [
        pytest.param(with_spend(disc="0.80"), id="0.80-spent-plus-0.20-estimate"),
        pytest.param(with_disc(duration_seconds=3000, approved_usd="1.00"), id="50-minute-disc"),
    ],
)
def test_launch_totalling_exactly_the_disc_cap_is_allowed(snapshot: LedgerSnapshot) -> None:
    assert evaluate(LAUNCH, snapshot, LIMITS).allowed is True


def test_launch_reaching_exactly_the_monthly_cap_is_allowed() -> None:
    assert evaluate(LAUNCH, with_spend(month="4.80"), LIMITS).allowed is True


def test_launch_over_the_monthly_cap_is_denied_by_r3() -> None:
    decision = evaluate(LAUNCH, with_spend(month="4.81"), LIMITS)

    assert_denied(decision, "R3")
    assert all(number in decision.reason for number in ("4.81", "0.20", "5.01", "5.00"))


@pytest.mark.parametrize(
    ("snapshot", "fragment"),
    [
        pytest.param(with_approval(consumed=True), "consumed", id="A5-approval-already-consumed"),
        pytest.param(with_approval(disc_id="disc-2"), "'disc-2'", id="issued-for-another-disc"),
        pytest.param(
            with_approval(action="request_approval"),
            "'request_approval'",
            id="issued-for-another-action",
        ),
        pytest.param(with_approval(status="rejected"), "'rejected'", id="status-rejected"),
        pytest.param(with_approval(status="pending"), "'pending'", id="status-pending"),
        pytest.param(with_approval(status="APPROVED"), "'APPROVED'", id="status-in-wrong-case"),
        pytest.param(
            dataclasses.replace(SNAPSHOT, approvals=()), "'apr-1'", id="no-approval-at-all"
        ),
        pytest.param(with_approval(ref="apr-9"), "'apr-1'", id="ref-names-no-approval"),
        pytest.param(with_approval(approved_usd=Decimal("0.19")), "0.19", id="covers-too-little"),
    ],
)
def test_launch_without_a_valid_approval_is_denied_by_r4(
    snapshot: LedgerSnapshot, fragment: str
) -> None:
    decision = evaluate(LAUNCH, snapshot, LIMITS)

    assert_denied(decision, "R4")
    assert fragment in decision.reason


def test_reason_for_an_approval_that_covers_too_little_includes_the_estimate() -> None:
    decision = evaluate(LAUNCH, with_approval(approved_usd=Decimal("0.19")), LIMITS)

    assert "0.20" in decision.reason


def test_approval_covering_more_than_the_estimate_is_allowed() -> None:
    assert evaluate(LAUNCH, with_approval(approved_usd=Decimal("0.50")), LIMITS).allowed is True


@pytest.mark.parametrize(
    ("snapshot", "rule"),
    [
        pytest.param(
            dataclasses.replace(with_spend(month="4.90", disc="0.90"), approvals=()),
            "R2",
            id="disc-cap-is-reported-before-monthly-cap-and-approval",
        ),
        pytest.param(
            dataclasses.replace(with_spend(month="4.90"), approvals=()),
            "R3",
            id="monthly-cap-is-reported-before-approval",
        ),
    ],
)
def test_first_failing_rule_is_reported(snapshot: LedgerSnapshot, rule: str) -> None:
    assert_denied(evaluate(LAUNCH, snapshot, LIMITS), rule)


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(ToolCall("read_ledger", {"limit": "10"}), id="read_ledger-with-argument"),
        pytest.param(ToolCall("list_pending", {"disc_id": "disc-1"}), id="list_pending-with-key"),
        pytest.param(ToolCall("request_approval", {}), id="request_approval-missing-disc_id"),
        pytest.param(
            ToolCall("request_approval", {"disc_id": "disc-1", "approved_usd": "9.99"}),
            id="request_approval-with-extra-key",
        ),
        pytest.param(
            ToolCall("request_approval", {"disc_id": 1}), id="request_approval-non-string-disc_id"
        ),
        pytest.param(
            ToolCall("request_approval", {"disc_id": "disc-404"}),
            id="request_approval-unknown-disc",
        ),
        pytest.param(ToolCall("launch_job", {}), id="launch_job-without-arguments"),
        pytest.param(
            ToolCall("launch_job", {"disc_id": "disc-1"}), id="launch_job-missing-approval_ref"
        ),
        pytest.param(
            ToolCall("launch_job", {"approval_ref": "apr-1"}), id="launch_job-missing-disc_id"
        ),
        pytest.param(
            ToolCall("launch_job", {**LAUNCH.arguments, "cost_usd": "0.01"}),
            id="launch_job-with-cost-as-string",
        ),
        pytest.param(
            ToolCall("launch_job", {**LAUNCH.arguments, "estimate_usd": Decimal("0.01")}),
            id="launch_job-with-cost-as-decimal",
        ),
        pytest.param(
            ToolCall("launch_job", {"disc_id": None, "approval_ref": "apr-1"}),
            id="launch_job-none-disc_id",
        ),
        pytest.param(
            ToolCall("launch_job", {"disc_id": "disc-1", "approval_ref": ["apr-1"]}),
            id="launch_job-list-approval_ref",
        ),
        pytest.param(
            ToolCall("launch_job", {"disc_id": "disc-404", "approval_ref": "apr-1"}),
            id="launch_job-unknown-disc",
        ),
        pytest.param(
            ToolCall("launch_job", cast("dict[str, object]", {1: "disc-1", 2: "apr-1"})),
            id="launch_job-non-string-keys",
        ),
        pytest.param(
            ToolCall("launch_job", cast("dict[str, object]", ["disc-1", "apr-1"])),
            id="launch_job-arguments-as-list",
        ),
        pytest.param(ToolCall(cast("str", None), {}), id="name-is-none"),
        pytest.param(ToolCall(cast("str", ["launch_job"]), {}), id="name-is-unhashable"),
        pytest.param(cast("ToolCall", None), id="call-is-none"),
        pytest.param(cast("ToolCall", {"name": "read_ledger"}), id="call-is-a-dict"),
    ],
)
def test_malformed_call_is_denied_by_r5_without_raising(call: ToolCall) -> None:
    assert_denied(evaluate(call, SNAPSHOT, LIMITS), "R5")


def test_reason_for_unexpected_arguments_names_them() -> None:
    call = ToolCall("launch_job", {**LAUNCH.arguments, "cost_usd": "0.01"})

    assert "'cost_usd'" in evaluate(call, SNAPSHOT, LIMITS).reason


@pytest.mark.parametrize(
    "snapshot",
    [
        pytest.param(cast("LedgerSnapshot", None), id="snapshot-is-none"),
        pytest.param(with_spend(month="NaN"), id="month-spend-is-nan"),
        pytest.param(with_spend(month="-1.00"), id="month-spend-is-negative"),
        pytest.param(with_spend(month="Infinity"), id="month-spend-is-infinite"),
        pytest.param(
            dataclasses.replace(SNAPSHOT, month_spend_usd=cast("Decimal", 0.5)),
            id="month-spend-is-a-float",
        ),
        pytest.param(with_spend(disc="-0.50"), id="disc-spend-is-negative"),
        pytest.param(
            dataclasses.replace(SNAPSHOT, disc_spend_usd=cast("dict[str, Decimal]", None)),
            id="disc-spend-is-none",
        ),
        pytest.param(
            dataclasses.replace(SNAPSHOT, discs=cast("tuple[Disc, ...]", None)), id="discs-is-none"
        ),
        pytest.param(
            dataclasses.replace(SNAPSHOT, discs=cast("tuple[Disc, ...]", ({"disc_id": "disc-1"},))),
            id="disc-is-a-dict",
        ),
        pytest.param(dataclasses.replace(SNAPSHOT, discs=(DISC, DISC)), id="duplicate-disc-id"),
        pytest.param(
            dataclasses.replace(SNAPSHOT, approvals=(APPROVAL, APPROVAL)),
            id="duplicate-approval-ref",
        ),
        pytest.param(with_approval(approved_usd=Decimal("NaN")), id="approved-amount-is-nan"),
        pytest.param(with_approval(approved_usd=Decimal("-1")), id="approved-amount-is-negative"),
        pytest.param(with_approval(consumed=None), id="consumed-is-none"),
        pytest.param(with_approval(status=None), id="status-is-none"),
        pytest.param(with_disc(duration_seconds=0, approved_usd="1.00"), id="zero-duration"),
        pytest.param(with_disc(duration_seconds=-600, approved_usd="1.00"), id="negative-duration"),
        pytest.param(
            dataclasses.replace(
                SNAPSHOT, discs=(dataclasses.replace(DISC, duration_seconds=cast("int", 600.0)),)
            ),
            id="duration-is-a-float",
        ),
        pytest.param(
            dataclasses.replace(
                SNAPSHOT, discs=(dataclasses.replace(DISC, duration_seconds=True),)
            ),
            id="duration-is-a-bool",
        ),
    ],
)
def test_launch_on_a_malformed_snapshot_is_denied_by_r5_without_raising(
    snapshot: LedgerSnapshot,
) -> None:
    assert_denied(evaluate(LAUNCH, snapshot, LIMITS), "R5")


@pytest.mark.parametrize(
    "limits",
    [
        pytest.param(cast("Limits", None), id="limits-is-none"),
        pytest.param(Limits(max_usd_per_disc=Decimal("NaN")), id="disc-cap-is-nan"),
        pytest.param(Limits(monthly_cap_usd=Decimal("-5.00")), id="monthly-cap-is-negative"),
        pytest.param(Limits(usd_per_minute=cast("Decimal", 0.02)), id="rate-is-a-float"),
        pytest.param(Limits(usd_per_minute=Decimal("0")), id="rate-is-zero"),
        pytest.param(Limits(usd_per_minute=Decimal("-0.02")), id="rate-is-negative"),
    ],
)
def test_launch_with_malformed_limits_is_denied_by_r5_without_raising(limits: Limits) -> None:
    assert_denied(evaluate(LAUNCH, SNAPSHOT, limits), "R5")


def test_request_approval_on_a_malformed_snapshot_is_denied_by_r5() -> None:
    call = ToolCall("request_approval", {"disc_id": "disc-1"})

    assert_denied(evaluate(call, with_spend(month="NaN"), LIMITS), "R5")
