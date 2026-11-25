from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from fareguard.gate.models import Approval, Disc
from fareguard.ledger import items
from fareguard.ledger.errors import LedgerDataError
from fareguard.ledger.store import ApprovalRequest, Launch, LedgerEvent

AT = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)
REQUEST = ApprovalRequest("disc-1", Decimal("0.20"), "apr-1", AT)
APPROVAL_ITEM: dict[str, Any] = {
    "pk": {"S": "APPROVAL"},
    "sk": {"S": "apr-1"},
    "action": {"S": "launch_job"},
    "disc_id": {"S": "disc-1"},
    "approved_usd": {"N": "0.20"},
    "status": {"S": "pending"},
    "consumed": {"BOOL": False},
    "requested_at": {"S": "2026-11-25T10:00:00+00:00"},
}
EVENT_ITEM: dict[str, Any] = {
    "pk": {"S": "EVENT"},
    "sk": {"S": "2026-11-25T10:00:00.000000+00:00#job_launched:apr-1"},
    "type": {"S": "job_launched"},
    "detail": {
        "M": {
            "disc_id": {"S": "disc-1"},
            "approval_ref": {"S": "apr-1"},
            "estimate_usd": {"N": "0.20"},
            "month": {"S": "2026-11"},
        }
    },
}
DISC_ITEM: dict[str, Any] = {
    "pk": {"S": "DISC"},
    "sk": {"S": "disc-1"},
    "duration_seconds": {"N": "600"},
}


def without(item: dict[str, Any], attribute: str) -> dict[str, Any]:
    return {name: value for name, value in item.items() if name != attribute}


@pytest.mark.parametrize(
    ("value", "stored"),
    [
        pytest.param("0.20", "0.20", id="keeps-trailing-zero"),
        pytest.param("5", "5", id="whole"),
        pytest.param("1E+2", "100", id="no-positive-exponent"),
        pytest.param("1E-7", "0.0000001", id="no-negative-exponent"),
        pytest.param("0.1", "0.1", id="exact-tenth"),
    ],
)
def test_amount_is_written_as_a_plain_decimal_number(value: str, stored: str) -> None:
    assert items.number(Decimal(value)) == {"N": stored}


def test_amount_survives_a_round_trip_exactly() -> None:
    written = {"spent_usd": items.number(Decimal("0.10") + Decimal("0.20"))}

    read = items.read_number(written, "spent_usd")

    assert type(read) is Decimal
    assert read == Decimal("0.30")
    assert str(read) == "0.30"


@pytest.mark.parametrize(
    ("stored", "read"),
    [
        pytest.param("0.2", "0.20", id="trailing-zero-dropped-by-dynamodb"),
        pytest.param("0.20", "0.20", id="already-two-places"),
        pytest.param("5", "5.00", id="whole-dollars"),
        pytest.param("0", "0.00", id="zero"),
        pytest.param("1E+2", "100.00", id="exponent"),
        pytest.param("0.200", "0.20", id="extra-zeros"),
    ],
)
def test_usd_amount_is_read_in_whole_cents_with_two_decimal_places(stored: str, read: str) -> None:
    amount = items.read_usd({"spent_usd": {"N": stored}}, "spent_usd")

    assert type(amount) is Decimal
    assert str(amount) == read


@pytest.mark.parametrize(
    "stored",
    [
        pytest.param({"N": "0.205"}, id="half-a-cent"),
        pytest.param({"N": "0.001"}, id="a-tenth-of-a-cent"),
        pytest.param({"N": "-0.20"}, id="negative"),
        pytest.param({"N": "NaN"}, id="not-a-number"),
        pytest.param({"N": "Infinity"}, id="infinite"),
        pytest.param({"N": "1E+30"}, id="too-large-to-express-in-cents"),
        pytest.param({"S": "0.20"}, id="a-string"),
    ],
)
def test_usd_amount_that_is_not_whole_cents_is_rejected_not_rounded(stored: dict[str, str]) -> None:
    with pytest.raises(LedgerDataError, match="spent_usd"):
        items.read_usd({"spent_usd": stored}, "spent_usd")


def test_missing_usd_amount_is_rejected() -> None:
    with pytest.raises(LedgerDataError, match="spent_usd"):
        items.read_usd({}, "spent_usd")


def test_stored_approval_amount_is_read_in_whole_cents() -> None:
    approval = items.read_approval({**APPROVAL_ITEM, "approved_usd": {"N": "0.2"}})

    assert str(approval.approved_usd) == "0.20"


def test_event_detail_reads_usd_amounts_in_whole_cents_and_other_numbers_as_stored() -> None:
    detail = {"estimate_usd": {"N": "0.2"}, "attempt": {"N": "3"}}

    event = items.read_event({**EVENT_ITEM, "detail": {"M": detail}})

    assert {name: str(value) for name, value in event.detail.items()} == {
        "estimate_usd": "0.20",
        "attempt": "3",
    }


def test_event_detail_with_a_usd_amount_that_is_not_whole_cents_is_rejected() -> None:
    detail = {"estimate_usd": {"N": "0.205"}}

    with pytest.raises(LedgerDataError, match="estimate_usd"):
        items.read_event({**EVENT_ITEM, "detail": {"M": detail}})


def test_key_holds_the_partition_and_sort_key_as_strings() -> None:
    assert items.key("DISC", "disc-1") == {"pk": {"S": "DISC"}, "sk": {"S": "disc-1"}}


def test_approval_request_becomes_the_approval_item_of_the_table() -> None:
    assert items.approval_item(REQUEST) == APPROVAL_ITEM


def test_event_becomes_the_event_item_of_the_table() -> None:
    event = Launch("disc-1", "apr-1", Decimal("0.20"), AT).event()

    assert items.event_item(event) == EVENT_ITEM


def test_stored_approval_is_read_back() -> None:
    assert items.read_approval(APPROVAL_ITEM) == REQUEST.approval()
    assert items.read_approval(APPROVAL_ITEM) == Approval(
        "apr-1", "launch_job", "disc-1", Decimal("0.20"), "pending", False
    )


def test_stored_event_is_read_back_with_its_detail_as_data() -> None:
    assert items.read_event(EVENT_ITEM) == LedgerEvent(
        at=AT,
        event_id="job_launched:apr-1",
        type="job_launched",
        detail={
            "disc_id": "disc-1",
            "approval_ref": "apr-1",
            "estimate_usd": Decimal("0.20"),
            "month": "2026-11",
        },
    )


def test_stored_disc_is_read_back() -> None:
    assert items.read_disc(DISC_ITEM) == Disc("disc-1", 600)


@pytest.mark.parametrize(
    ("item", "attribute"),
    [
        pytest.param(without(APPROVAL_ITEM, "status"), "status", id="missing-status"),
        pytest.param(without(APPROVAL_ITEM, "consumed"), "consumed", id="missing-consumed"),
        pytest.param({**APPROVAL_ITEM, "consumed": {"S": "no"}}, "consumed", id="consumed-string"),
        pytest.param(
            {**APPROVAL_ITEM, "approved_usd": {"S": "0.20"}}, "approved_usd", id="amount-as-string"
        ),
        pytest.param(
            {**APPROVAL_ITEM, "approved_usd": {"N": "lots"}},
            "approved_usd",
            id="amount-not-number",
        ),
        pytest.param({**APPROVAL_ITEM, "action": {"S": 7}}, "action", id="action-not-text"),
        pytest.param({**APPROVAL_ITEM, "disc_id": "disc-1"}, "disc_id", id="untyped-attribute"),
    ],
)
def test_malformed_approval_item_is_rejected(item: dict[str, Any], attribute: str) -> None:
    with pytest.raises(LedgerDataError, match=repr(attribute)):
        items.read_approval(item)


@pytest.mark.parametrize(
    "duration",
    [
        pytest.param({"N": "600.5"}, id="fraction"),
        pytest.param({"N": "NaN"}, id="nan"),
        pytest.param({"N": "Infinity"}, id="infinite"),
        pytest.param({"S": "600"}, id="string"),
    ],
)
def test_disc_item_without_a_whole_duration_is_rejected(duration: dict[str, str]) -> None:
    with pytest.raises(LedgerDataError, match="duration_seconds"):
        items.read_disc({**DISC_ITEM, "duration_seconds": duration})


@pytest.mark.parametrize(
    ("item", "attribute"),
    [
        pytest.param({**EVENT_ITEM, "sk": {"S": "yesterday#job_launched:apr-1"}}, "sk", id="time"),
        pytest.param(without(EVENT_ITEM, "type"), "type", id="missing-type"),
        pytest.param({**EVENT_ITEM, "detail": {"S": "text"}}, "detail", id="detail-not-a-map"),
        pytest.param(
            {**EVENT_ITEM, "detail": {"M": {"estimate_usd": {"BOOL": True}}}},
            "estimate_usd",
            id="detail-value-neither-text-nor-number",
        ),
    ],
)
def test_malformed_event_item_is_rejected(item: dict[str, Any], attribute: str) -> None:
    with pytest.raises(LedgerDataError, match=repr(attribute)):
        items.read_event(item)
