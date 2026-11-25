"""Conversion between ledger values and the items of the DynamoDB table.

    pk "DISC",     sk <disc_id>:  duration_seconds, spent_usd, pending_approval_ref
    pk "APPROVAL", sk <ref>:      action, disc_id, approved_usd, status, consumed, requested_at
    pk "SPEND",    sk <YYYY-MM>:  spent_usd
    pk "EVENT",    sk <ISO timestamp>#<id>:  type, detail

Amounts are DynamoDB numbers, written from and read into Decimal, never float.
See docs/decisions/0002-single-table-ledger-with-atomic-launch.md.
"""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from fareguard.gate.models import Approval, Disc
from fareguard.ledger.errors import LedgerDataError
from fareguard.ledger.store import ApprovalRequest, LedgerEvent, event_sort_key

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.type_defs import AttributeValueTypeDef

type StoredItem = Mapping[str, Any]
type NewItem = dict[str, AttributeValueTypeDef]

DISC = "DISC"
APPROVAL = "APPROVAL"
SPEND = "SPEND"
EVENT = "EVENT"


def text(value: str) -> "AttributeValueTypeDef":
    """Return `value` as a DynamoDB string."""
    return {"S": value}


def number(value: Decimal) -> "AttributeValueTypeDef":
    """Return `value` as a DynamoDB number, in plain notation so no exponent is sent."""
    return {"N": format(value, "f")}


def key(pk: str, sk: str) -> "NewItem":
    """Return the primary key of one item."""
    return {"pk": text(pk), "sk": text(sk)}


def approval_item(request: ApprovalRequest) -> "NewItem":
    """Return the item of the pending approval that `request` creates."""
    approval = request.approval()
    return {
        **key(APPROVAL, approval.ref),
        "action": text(approval.action),
        "disc_id": text(approval.disc_id),
        "approved_usd": number(approval.approved_usd),
        "status": text(approval.status),
        "consumed": {"BOOL": approval.consumed},
        "requested_at": text(request.at.isoformat()),
    }


def event_item(event: LedgerEvent) -> "NewItem":
    """Return the item of `event`. Its detail is stored as data: strings and numbers."""
    detail: NewItem = {
        name: text(value) if isinstance(value, str) else number(value)
        for name, value in event.detail.items()
    }
    return {**key(EVENT, event_sort_key(event)), "type": text(event.type), "detail": {"M": detail}}


def _read(item: StoredItem, attribute: str, kind: str, expected: type) -> Any:  # noqa: ANN401  # the caller names the type it expects
    try:
        value = item[attribute][kind]
    except (KeyError, TypeError) as error:
        raise LedgerDataError(attribute) from error
    if not isinstance(value, expected):
        raise LedgerDataError(attribute)
    return value


def read_text(item: StoredItem, attribute: str) -> str:
    """Return a string attribute.

    Raises:
        LedgerDataError: if the attribute is missing or is not a string.
    """
    value: str = _read(item, attribute, "S", str)
    return value


def read_number(item: StoredItem, attribute: str) -> Decimal:
    """Return a number attribute as a Decimal.

    Raises:
        LedgerDataError: if the attribute is missing or is not a number.
    """
    try:
        return Decimal(_read(item, attribute, "N", str))
    except InvalidOperation as error:
        raise LedgerDataError(attribute) from error


def read_disc(item: StoredItem) -> Disc:
    """Return the disc stored in `item`.

    Raises:
        LedgerDataError: if an attribute is missing or the duration is not a whole number.
    """
    duration = read_number(item, "duration_seconds")
    if not duration.is_finite() or duration != duration.to_integral_value():
        raise LedgerDataError("duration_seconds")
    return Disc(read_text(item, "sk"), int(duration))


def read_approval(item: StoredItem) -> Approval:
    """Return the approval stored in `item`.

    Raises:
        LedgerDataError: if an attribute is missing or has the wrong type.
    """
    consumed: bool = _read(item, "consumed", "BOOL", bool)
    return Approval(
        ref=read_text(item, "sk"),
        action=read_text(item, "action"),
        disc_id=read_text(item, "disc_id"),
        approved_usd=read_number(item, "approved_usd"),
        status=read_text(item, "status"),
        consumed=consumed,
    )


def read_event(item: StoredItem) -> LedgerEvent:
    """Return the event stored in `item`, with its detail as plain data.

    Raises:
        LedgerDataError: if an attribute is missing or the sort key holds no timestamp.
    """
    timestamp, _, event_id = read_text(item, "sk").partition("#")
    stored: Mapping[str, StoredItem] = _read(item, "detail", "M", Mapping)
    detail: dict[str, str | Decimal] = {
        name: read_text(stored, name) if "S" in value else read_number(stored, name)
        for name, value in stored.items()
    }
    try:
        at = datetime.fromisoformat(timestamp)
    except ValueError as error:
        raise LedgerDataError("sk") from error
    return LedgerEvent(at, event_id, read_text(item, "type"), detail)
