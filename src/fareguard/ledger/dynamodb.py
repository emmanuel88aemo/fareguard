"""The ledger store on one DynamoDB table. Every write is a single transaction."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from fareguard.gate.models import Approval, LedgerSnapshot, Limits
from fareguard.ledger import items
from fareguard.ledger.errors import (
    ApprovalRefExistsError,
    LedgerTransactionError,
    PendingApprovalExistsError,
    UnknownDiscError,
)
from fareguard.ledger.store import (
    APPROVED,
    LAUNCH_JOB,
    LAUNCHED,
    NO_SPEND_USD,
    PENDING,
    ApprovalRequest,
    Launch,
    LaunchCheck,
    LaunchResult,
    LedgerEvent,
    month_of,
    refuse,
    require_event_limit,
    require_limits,
)

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient
    from mypy_boto3_dynamodb.type_defs import TransactWriteItemTypeDef

_CONDITION_FAILED = "ConditionalCheckFailed"
_NOT_FAILED = "None"
_IF_NEW = "attribute_not_exists(pk)"
_APPROVAL_COVERS_LAUNCH = (
    "#status = :approved AND #consumed = :false AND #action = :launch_job "
    "AND disc_id = :disc_id AND approved_usd >= :estimate"
)
# status, consumed and action are reserved words in DynamoDB expressions.
_APPROVAL_NAMES = {"#status": "status", "#consumed": "consumed", "#action": "action"}


def _failed(reason: items.StoredItem) -> bool:
    return bool(reason["Code"] == _CONDITION_FAILED)


class DynamoLedgerStore:
    """A LedgerStore on DynamoDB. The client is injected; this module creates none."""

    def __init__(self, table_name: str, client: "DynamoDBClient") -> None:
        """Use `client` to read and write the table `table_name`."""
        self._table = table_name
        self._client = client

    def snapshot(self, at: datetime) -> LedgerSnapshot:
        """Return discs, approvals and spend as the gate reads them, for the UTC month of `at`.

        The reads are strongly consistent but separate, so the snapshot is not
        one point in time. The launch transaction, not the snapshot, enforces the rules.
        """
        month = month_of(at)
        discs = self._query(items.DISC)
        spend = self._client.get_item(
            TableName=self._table, Key=items.key(items.SPEND, month), ConsistentRead=True
        ).get("Item")
        return LedgerSnapshot(
            discs=tuple(items.read_disc(item) for item in discs),
            approvals=self._approvals(),
            month_spend_usd=NO_SPEND_USD if spend is None else items.read_usd(spend, "spent_usd"),
            disc_spend_usd={
                items.read_text(item, "sk"): items.read_usd(item, "spent_usd")
                for item in discs
                if "spent_usd" in item
            },
        )

    def recent_events(self, limit: int) -> tuple[LedgerEvent, ...]:
        """Return up to `limit` events, newest first."""
        require_event_limit(limit)
        return tuple(items.read_event(item) for item in self._query(items.EVENT, newest=limit))

    def pending_approvals(self) -> tuple[Approval, ...]:
        """Return the approval requests awaiting a decision, ordered by ref."""
        return tuple(approval for approval in self._approvals() if approval.status == PENDING)

    def create_approval_request(
        self, disc_id: str, approved_usd: Decimal, ref: str, at: datetime
    ) -> None:
        """Write the approval, the mark on its disc and the event, or nothing."""
        request = ApprovalRequest(disc_id, approved_usd, ref, at)
        reasons = self._transact(
            [
                self._put_if_new(items.approval_item(request)),
                {
                    "Update": {
                        "TableName": self._table,
                        "Key": items.key(items.DISC, disc_id),
                        "UpdateExpression": "SET pending_approval_ref = :ref",
                        "ConditionExpression": "attribute_exists(pk) "
                        "AND attribute_not_exists(pending_approval_ref)",
                        "ExpressionAttributeValues": {":ref": items.text(ref)},
                        "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
                    }
                },
                self._put_if_new(items.event_item(request.event())),
            ]
        )
        if reasons is None:
            return
        approval, disc, _ = reasons
        if _failed(approval):
            raise ApprovalRefExistsError(ref)
        if _failed(disc) and "Item" not in disc:
            raise UnknownDiscError(disc_id)
        if _failed(disc):
            raise PendingApprovalExistsError(disc_id)
        raise LedgerTransactionError(["the event of this request already exists"])

    def record_launch(self, launch: Launch, limits: Limits) -> LaunchResult:
        """Apply the launch in one transaction of four writes, or change nothing and say why."""
        require_limits(limits)
        reasons = self._transact(
            [
                self._consume_approval(launch),
                self._add_spend(items.DISC, launch.disc_id, launch, limits.max_usd_per_disc),
                self._add_spend(items.SPEND, launch.month, launch, limits.monthly_cap_usd),
                self._put_if_new(items.event_item(launch.event())),
            ]
        )
        if reasons is None:
            return LAUNCHED
        approval, disc, spend, event = reasons
        checks = {
            # A failed condition returns the old item only if the item exists.
            LaunchCheck.UNKNOWN_DISC: _failed(disc) and "Item" not in disc,
            LaunchCheck.DISC_CAP: _failed(disc) and "Item" in disc,
            LaunchCheck.MONTH_CAP: _failed(spend),
            LaunchCheck.APPROVAL: _failed(approval),
            LaunchCheck.DUPLICATE_EVENT: _failed(event),
        }
        return refuse(check for check, failed in checks.items() if failed)

    def _consume_approval(self, launch: Launch) -> "TransactWriteItemTypeDef":
        return {
            "Update": {
                "TableName": self._table,
                "Key": items.key(items.APPROVAL, launch.approval_ref),
                "UpdateExpression": "SET #consumed = :true",
                "ConditionExpression": _APPROVAL_COVERS_LAUNCH,
                "ExpressionAttributeNames": _APPROVAL_NAMES,
                "ExpressionAttributeValues": {
                    ":true": {"BOOL": True},
                    ":false": {"BOOL": False},
                    ":approved": items.text(APPROVED),
                    ":launch_job": items.text(LAUNCH_JOB),
                    ":disc_id": items.text(launch.disc_id),
                    ":estimate": items.number(launch.estimate_usd),
                },
            }
        }

    def _add_spend(
        self, pk: str, sk: str, launch: Launch, cap_usd: Decimal
    ) -> "TransactWriteItemTypeDef":
        """Add the estimate to `spent_usd` only if the new total stays within the cap.

        A condition cannot add, so the cap is checked as "spent <= cap - estimate".
        An item with no spend yet counts as zero, unless the estimate alone is
        over the cap. A disc must already exist; a month is created on first use.
        """
        room = cap_usd - launch.estimate_usd
        condition = "spent_usd <= :room"
        if room >= Decimal("0"):
            condition = f"(attribute_not_exists(spent_usd) OR {condition})"
        if pk == items.DISC:
            condition = f"attribute_exists(pk) AND {condition}"
        return {
            "Update": {
                "TableName": self._table,
                "Key": items.key(pk, sk),
                "UpdateExpression": "ADD spent_usd :estimate",
                "ConditionExpression": condition,
                "ExpressionAttributeValues": {
                    ":estimate": items.number(launch.estimate_usd),
                    ":room": items.number(room),
                },
                "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
            }
        }

    def _put_if_new(self, item: "items.NewItem") -> "TransactWriteItemTypeDef":
        return {"Put": {"TableName": self._table, "Item": item, "ConditionExpression": _IF_NEW}}

    def _transact(self, writes: list["TransactWriteItemTypeDef"]) -> list[items.StoredItem] | None:
        """Apply `writes` atomically in one call. Return None, or one cancellation reason per write.

        Raises:
            LedgerTransactionError: if a write was cancelled for anything but its condition.
        """
        try:
            self._client.transact_write_items(TransactItems=writes)
        except self._client.exceptions.TransactionCanceledException as error:
            response: items.StoredItem = error.response
            reasons: list[items.StoredItem] = list(response.get("CancellationReasons", []))
            codes = [str(reason.get("Code")) for reason in reasons]
            if len(codes) != len(writes) or set(codes) - {_CONDITION_FAILED, _NOT_FAILED}:
                raise LedgerTransactionError(codes) from error
            return reasons
        return None

    def _approvals(self) -> tuple[Approval, ...]:
        return tuple(items.read_approval(item) for item in self._query(items.APPROVAL))

    def _query(self, pk: str, newest: int | None = None) -> list[items.StoredItem]:
        """Return every item under `pk` in key order, or only the `newest` ones, latest first."""
        found: list[items.StoredItem] = []
        arguments: dict[str, Any] = {
            "TableName": self._table,
            "KeyConditionExpression": "pk = :pk",
            "ExpressionAttributeValues": {":pk": items.text(pk)},
            "ConsistentRead": True,
            "ScanIndexForward": newest is None,
        }
        while True:
            if newest is not None:
                arguments["Limit"] = newest - len(found)
            page = self._client.query(**arguments)
            found.extend(page["Items"])
            if "LastEvaluatedKey" not in page or len(found) == newest:
                return found
            arguments["ExclusiveStartKey"] = page["LastEvaluatedKey"]
