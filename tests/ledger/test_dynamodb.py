from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from botocore.exceptions import ClientError

from fareguard.gate.models import Approval, Disc, Limits
from fareguard.ledger import dynamodb
from fareguard.ledger.dynamodb import DynamoLedgerStore
from fareguard.ledger.errors import LedgerDataError, LedgerTransactionError
from fareguard.ledger.store import Launch, LedgerStore

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient

AT = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)
LIMITS = Limits()
ESTIMATE = Decimal("0.20")
LAUNCH = Launch("disc-1", "apr-1", ESTIMATE, AT)
LAUNCH_EVENT_KEY = "2026-11-25T10:00:00.000000+00:00#job_launched:apr-1"
REQUEST_EVENT_KEY = "2026-11-25T10:00:00.000000+00:00#approval_requested:apr-2"
DISC_ITEM = {"pk": {"S": "DISC"}, "sk": {"S": "disc-1"}, "duration_seconds": {"N": "600"}}
APPROVAL_ITEM = {
    "pk": {"S": "APPROVAL"},
    "sk": {"S": "apr-1"},
    "action": {"S": "launch_job"},
    "disc_id": {"S": "disc-1"},
    "approved_usd": {"N": "0.20"},
    "status": {"S": "approved"},
    "consumed": {"BOOL": False},
    "requested_at": {"S": "2026-11-24T09:00:00+00:00"},
}


class Table:
    """Raw access to the moto table, so tests see what is stored and not what the store says."""

    def __init__(self, client: "DynamoDBClient", name: str) -> None:
        self.client = client
        self.name = name
        self.transactions: list[list[dict[str, Any]]] = []

    def put(self, *items: dict[str, Any]) -> None:
        for item in items:
            self.client.put_item(TableName=self.name, Item=item)

    def all(self) -> dict[str, dict[str, Any]]:
        stored = self.client.scan(TableName=self.name, ConsistentRead=True)["Items"]
        return {f"{item['pk']['S']}/{item['sk']['S']}": dict(item) for item in stored}


@pytest.fixture
def table(
    dynamodb_client: "DynamoDBClient", table_name: str, monkeypatch: pytest.MonkeyPatch
) -> Table:
    """The raw table, recording every TransactWriteItems call the store makes."""
    table = Table(dynamodb_client, table_name)
    real = dynamodb_client.transact_write_items

    def recording(**arguments: Any) -> Any:  # noqa: ANN401  # mirrors the client's own signature
        table.transactions.append(arguments["TransactItems"])
        return real(**arguments)

    monkeypatch.setattr(dynamodb_client, "transact_write_items", recording)
    return table


@pytest.fixture
def store(table: Table) -> DynamoLedgerStore:
    return DynamoLedgerStore(table.name, table.client)


def cancelled(client: "DynamoDBClient", *codes: str) -> ClientError:
    """Build the error DynamoDB raises when it cancels a transaction with these reason codes."""
    response: Any = {
        "Error": {"Code": "TransactionCanceledException", "Message": "cancelled"},
        "CancellationReasons": [{"Code": code} for code in codes],
    }
    return client.exceptions.TransactionCanceledException(response, "TransactWriteItems")


def test_dynamo_store_satisfies_the_protocol(store: DynamoLedgerStore) -> None:
    typed: LedgerStore = store

    assert typed.pending_approvals() == ()


def test_module_creates_no_client_and_reads_no_environment() -> None:
    assert not hasattr(dynamodb, "boto3")
    assert not hasattr(dynamodb, "os")


def test_launch_is_one_transaction_of_four_writes(table: Table, store: DynamoLedgerStore) -> None:
    table.put(DISC_ITEM, APPROVAL_ITEM)

    assert store.record_launch(LAUNCH, LIMITS).launched is True

    (writes,) = table.transactions
    assert [next(iter(write)) for write in writes] == ["Update", "Update", "Update", "Put"]
    assert [next(iter(write.values()))["TableName"] for write in writes] == [table.name] * 4
    assert all("ConditionExpression" in next(iter(write.values())) for write in writes)


def test_refused_launch_is_one_transaction_and_is_not_retried(
    table: Table, store: DynamoLedgerStore
) -> None:
    table.put(DISC_ITEM, {**APPROVAL_ITEM, "consumed": {"BOOL": True}})

    assert store.record_launch(LAUNCH, LIMITS).rule == "R4"

    assert len(table.transactions) == 1


def test_launch_stores_the_four_items_of_the_table_layout(
    table: Table, store: DynamoLedgerStore
) -> None:
    table.put(DISC_ITEM, APPROVAL_ITEM)

    store.record_launch(LAUNCH, LIMITS)

    assert table.all() == {
        "APPROVAL/apr-1": {**APPROVAL_ITEM, "consumed": {"BOOL": True}},
        "DISC/disc-1": {**DISC_ITEM, "spent_usd": {"N": "0.20"}},
        "SPEND/2026-11": {
            "pk": {"S": "SPEND"},
            "sk": {"S": "2026-11"},
            "spent_usd": {"N": "0.20"},
        },
        f"EVENT/{LAUNCH_EVENT_KEY}": {
            "pk": {"S": "EVENT"},
            "sk": {"S": LAUNCH_EVENT_KEY},
            "type": {"S": "job_launched"},
            "detail": {
                "M": {
                    "disc_id": {"S": "disc-1"},
                    "approval_ref": {"S": "apr-1"},
                    "estimate_usd": {"N": "0.20"},
                    "month": {"S": "2026-11"},
                }
            },
        },
    }


def test_spend_is_added_as_an_exact_decimal_number(table: Table, store: DynamoLedgerStore) -> None:
    table.put(
        {**DISC_ITEM, "spent_usd": {"N": "0.10"}},
        APPROVAL_ITEM,
        {"pk": {"S": "SPEND"}, "sk": {"S": "2026-11"}, "spent_usd": {"N": "0.10"}},
    )

    store.record_launch(LAUNCH, LIMITS)

    stored = table.all()
    assert Decimal(stored["DISC/disc-1"]["spent_usd"]["N"]) == Decimal("0.30")
    assert Decimal(stored["SPEND/2026-11"]["spent_usd"]["N"]) == Decimal("0.30")


def test_approval_request_is_one_transaction_of_three_writes(
    table: Table, store: DynamoLedgerStore
) -> None:
    table.put(DISC_ITEM)

    store.create_approval_request("disc-1", ESTIMATE, "apr-2", AT)

    (writes,) = table.transactions
    assert [next(iter(write)) for write in writes] == ["Put", "Update", "Put"]
    assert table.all() == {
        "APPROVAL/apr-2": {
            **APPROVAL_ITEM,
            "sk": {"S": "apr-2"},
            "status": {"S": "pending"},
            "requested_at": {"S": "2026-11-25T10:00:00+00:00"},
        },
        "DISC/disc-1": {**DISC_ITEM, "pending_approval_ref": {"S": "apr-2"}},
        f"EVENT/{REQUEST_EVENT_KEY}": {
            "pk": {"S": "EVENT"},
            "sk": {"S": REQUEST_EVENT_KEY},
            "type": {"S": "approval_requested"},
            "detail": {
                "M": {
                    "disc_id": {"S": "disc-1"},
                    "approval_ref": {"S": "apr-2"},
                    "approved_usd": {"N": "0.20"},
                }
            },
        },
    }


def test_request_whose_event_already_exists_is_cancelled_and_changes_nothing(
    table: Table, store: DynamoLedgerStore
) -> None:
    table.put(DISC_ITEM, {"pk": {"S": "EVENT"}, "sk": {"S": REQUEST_EVENT_KEY}})
    before = table.all()

    with pytest.raises(LedgerTransactionError, match="already exists"):
        store.create_approval_request("disc-1", ESTIMATE, "apr-2", AT)

    assert table.all() == before


def test_launch_whose_event_already_exists_is_refused_and_changes_nothing(
    table: Table, store: DynamoLedgerStore
) -> None:
    table.put(DISC_ITEM, APPROVAL_ITEM, {"pk": {"S": "EVENT"}, "sk": {"S": LAUNCH_EVENT_KEY}})
    before = table.all()

    assert store.record_launch(LAUNCH, LIMITS).rule == "R5"

    assert table.all() == before


@pytest.mark.parametrize(
    "codes",
    [
        pytest.param(("TransactionConflict", "None", "None", "None"), id="conflict"),
        pytest.param(("None", "ThrottlingError", "None", "None"), id="throttled"),
        pytest.param(("ConditionalCheckFailed", "TransactionConflict", "None", "None"), id="mixed"),
        pytest.param(("ConditionalCheckFailed",), id="fewer-reasons-than-writes"),
        pytest.param((), id="no-reasons"),
    ],
)
def test_cancellation_that_is_not_a_failed_condition_raises_without_a_retry(
    table: Table, store: DynamoLedgerStore, monkeypatch: pytest.MonkeyPatch, codes: tuple[str, ...]
) -> None:
    calls: list[object] = []

    def cancel(**arguments: object) -> None:
        calls.append(arguments)
        raise cancelled(table.client, *codes)

    monkeypatch.setattr(table.client, "transact_write_items", cancel)

    with pytest.raises(LedgerTransactionError, match="nothing changed"):
        store.record_launch(LAUNCH, LIMITS)

    assert len(calls) == 1


def test_other_client_errors_are_not_swallowed(dynamodb_client: "DynamoDBClient") -> None:
    store = DynamoLedgerStore("no-such-table", dynamodb_client)

    with pytest.raises(ClientError, match="ResourceNotFoundException"):
        store.record_launch(LAUNCH, LIMITS)


def test_reads_follow_every_page(table: Table, monkeypatch: pytest.MonkeyPatch) -> None:
    discs = [Disc(f"disc-{number}", 600) for number in range(1, 6)]
    for disc in discs:
        table.put({**DISC_ITEM, "sk": {"S": disc.disc_id}})
        ref, disc_id = {"S": f"apr-{disc.disc_id}"}, {"S": disc.disc_id}
        table.put({**APPROVAL_ITEM, "sk": ref, "disc_id": disc_id})
    store = DynamoLedgerStore(table.name, table.client)
    for disc in discs:
        store.record_launch(Launch(disc.disc_id, f"apr-{disc.disc_id}", ESTIMATE, AT), LIMITS)
    real = table.client.query
    pages: list[int] = []

    def one_item_per_page(**arguments: Any) -> Any:  # noqa: ANN401  # mirrors the client's own signature
        page = real(**{**arguments, "Limit": 1})
        pages.append(len(page["Items"]))
        return page

    monkeypatch.setattr(table.client, "query", one_item_per_page)

    snapshot = store.snapshot(AT)
    events = store.recent_events(3)

    assert snapshot.discs == tuple(discs)
    assert [a.ref for a in snapshot.approvals] == [f"apr-{disc.disc_id}" for disc in discs]
    assert len(events) == 3
    assert max(pages) == 1


def test_malformed_stored_item_stops_a_snapshot(table: Table, store: DynamoLedgerStore) -> None:
    table.put({**DISC_ITEM, "duration_seconds": {"S": "ten minutes"}})

    with pytest.raises(LedgerDataError, match="duration_seconds"):
        store.snapshot(AT)


def test_approval_seeded_by_hand_is_read_as_an_approval(
    table: Table, store: DynamoLedgerStore
) -> None:
    table.put(APPROVAL_ITEM)

    assert store.snapshot(AT).approvals == (
        Approval("apr-1", "launch_job", "disc-1", ESTIMATE, "approved", False),
    )


def test_amounts_stored_without_trailing_zeros_are_read_in_whole_cents(
    table: Table, store: DynamoLedgerStore
) -> None:
    """Real DynamoDB stores 0.20 as "0.2"; moto keeps what it is given, so write it that way."""
    table.put(
        {**DISC_ITEM, "spent_usd": {"N": "0.2"}},
        {**APPROVAL_ITEM, "approved_usd": {"N": "0.2"}},
        {"pk": {"S": "SPEND"}, "sk": {"S": "2026-11"}, "spent_usd": {"N": "1"}},
    )

    snapshot = store.snapshot(AT)

    assert snapshot.disc_spend_usd == {"disc-1": Decimal("0.20")}
    assert str(snapshot.disc_spend_usd["disc-1"]) == "0.20"
    assert str(snapshot.approvals[0].approved_usd) == "0.20"
    assert str(snapshot.month_spend_usd) == "1.00"


def test_month_with_no_spend_reads_as_zero_with_two_decimal_places(
    store: DynamoLedgerStore,
) -> None:
    assert str(store.snapshot(AT).month_spend_usd) == "0.00"


@pytest.mark.parametrize(
    "item",
    [
        pytest.param({**DISC_ITEM, "spent_usd": {"N": "0.205"}}, id="disc-spend"),
        pytest.param(
            {"pk": {"S": "SPEND"}, "sk": {"S": "2026-11"}, "spent_usd": {"N": "0.205"}},
            id="month-spend",
        ),
        pytest.param({**APPROVAL_ITEM, "approved_usd": {"N": "0.205"}}, id="approved-amount"),
    ],
)
def test_stored_amount_that_is_not_whole_cents_stops_a_snapshot(
    table: Table, store: DynamoLedgerStore, item: dict[str, Any]
) -> None:
    table.put(item)

    with pytest.raises(LedgerDataError, match="_usd"):
        store.snapshot(AT)
