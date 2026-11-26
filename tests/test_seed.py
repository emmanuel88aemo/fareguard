import json
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
import pytest
from moto import mock_aws

import seed
from fareguard.ledger.dynamodb import DynamoLedgerStore
from fareguard.ops.seed_data import PLANTED_INSTRUCTION, SEED_DISCS

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient

NOW = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
TABLE = "fareguard-test-ledger"
# A made-up ARN with the shape of a real one; the account is twelve zeros.
OUTPUTS: Mapping[str, object] = {
    "ledger_table_name": TABLE,
    "ledger_table_arn": f"arn:aws:dynamodb:us-east-1:000000000000:table/{TABLE}",
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator["DynamoDBClient"]:
    """A client for an empty ledger table in moto. Fake credentials keep it away from AWS."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with mock_aws():
        dynamodb = boto3.client("dynamodb", region_name="us-east-1")
        dynamodb.create_table(
            TableName=TABLE,
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
        )
        yield dynamodb


def _outputs(_directory: Path) -> Mapping[str, object]:
    return OUTPUTS


def _run(argv: list[str], client: "DynamoDBClient") -> int:
    return seed.main(
        argv, read_outputs=_outputs, make_client=lambda _table: client, now=lambda: NOW
    )


def _count(client: "DynamoDBClient") -> int:
    return client.scan(TableName=TABLE, Select="COUNT", ConsistentRead=True)["Count"]


def test_seed_writes_the_fixture_discs_with_no_spend_and_no_approval(
    client: "DynamoDBClient",
) -> None:
    code = _run(["seed"], client)

    snapshot = DynamoLedgerStore(TABLE, client).snapshot(NOW)
    assert code == 0
    assert sorted(snapshot.discs, key=lambda disc: disc.disc_id) == sorted(
        SEED_DISCS, key=lambda disc: disc.disc_id
    )
    assert snapshot.approvals == ()
    assert snapshot.disc_spend_usd == {}
    assert snapshot.month_spend_usd == Decimal("0.00")


def test_seed_plants_one_event_that_the_store_reads_as_data(client: "DynamoDBClient") -> None:
    _run(["seed"], client)

    (event,) = DynamoLedgerStore(TABLE, client).recent_events(20)
    assert event.at == NOW
    assert event.detail["note"] == PLANTED_INSTRUCTION


def test_seed_prints_what_it_wrote(
    client: "DynamoDBClient", capsys: pytest.CaptureFixture[str]
) -> None:
    _run(["seed"], client)

    printed = capsys.readouterr().out
    assert "wrote disc disc-001: 30 minutes" in printed
    assert "wrote disc disc-long: 75 minutes" in printed
    assert PLANTED_INSTRUCTION in printed
    assert len(printed.splitlines()) == len(SEED_DISCS) + 1


def test_seed_never_replaces_a_disc_that_exists(
    client: "DynamoDBClient", capsys: pytest.CaptureFixture[str]
) -> None:
    _run(["seed"], client)
    store = DynamoLedgerStore(TABLE, client)
    store.create_approval_request("disc-001", Decimal("0.60"), "apr-1", NOW)
    before = _count(client)
    capsys.readouterr()

    code = _run(["seed"], client)

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "disc-001 is already in" in captured.err
    assert "reset --yes" in captured.err
    assert _count(client) == before
    with pytest.raises(Exception, match="already has a pending approval request"):
        store.create_approval_request("disc-001", Decimal("0.60"), "apr-2", NOW)


def test_reset_without_yes_is_refused_and_deletes_nothing(
    client: "DynamoDBClient", capsys: pytest.CaptureFixture[str]
) -> None:
    _run(["seed"], client)
    capsys.readouterr()

    code = seed.main(["reset"], read_outputs=_no_outputs, make_client=_no_client)

    captured = capsys.readouterr()
    assert code == 1
    assert "--yes" in captured.err
    assert _count(client) == len(SEED_DISCS) + 1


def test_reset_with_yes_deletes_every_item_and_prints_how_many(
    client: "DynamoDBClient", capsys: pytest.CaptureFixture[str]
) -> None:
    _run(["seed"], client)
    DynamoLedgerStore(TABLE, client).create_approval_request(
        "disc-001", Decimal("0.60"), "apr-1", NOW
    )
    capsys.readouterr()

    code = _run(["reset", "--yes"], client)

    assert code == 0
    # Four discs and the planted event, then the approval and the event of its request.
    assert capsys.readouterr().out == f"deleted 7 item(s) from {TABLE}\n"
    assert _count(client) == 0


def test_reset_of_an_empty_table_deletes_nothing(
    client: "DynamoDBClient", capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run(["reset", "--yes"], client)

    assert code == 0
    assert capsys.readouterr().out == f"deleted 0 item(s) from {TABLE}\n"


def test_a_table_can_be_seeded_again_after_a_reset(client: "DynamoDBClient") -> None:
    _run(["seed"], client)
    _run(["reset", "--yes"], client)

    assert _run(["seed"], client) == 0
    assert _count(client) == len(SEED_DISCS) + 1


def test_show_prints_the_ledger_as_the_read_tool_presents_it(
    client: "DynamoDBClient", capsys: pytest.CaptureFixture[str]
) -> None:
    _run(["seed"], client)
    capsys.readouterr()

    code = _run(["show"], client)

    view = json.loads(capsys.readouterr().out)
    assert code == 0
    assert {"disc_id": "disc-long", "duration_seconds": 4500, "spent_usd": "0.00"} in view["discs"]
    assert (view["month"], view["month_spent_usd"]) == ("2026-11", "0.00")
    assert view["month_remaining_usd"] == "5.00"
    assert [event["detail"]["note"] for event in view["untrusted_ledger_events"]] == [
        PLANTED_INSTRUCTION
    ]


def test_show_of_a_malformed_ledger_prints_the_refusal_and_fails(
    client: "DynamoDBClient", capsys: pytest.CaptureFixture[str]
) -> None:
    client.put_item(
        TableName=TABLE,
        Item={"pk": {"S": "DISC"}, "sk": {"S": "Not A Disc"}, "duration_seconds": {"N": "60"}},
    )

    code = _run(["show"], client)

    assert code == 1
    assert json.loads(capsys.readouterr().out)["rule"] == "R5"


@pytest.mark.parametrize("command", [["seed"], ["reset", "--yes"], ["show"]])
@pytest.mark.parametrize("missing", sorted(OUTPUTS))
def test_a_missing_output_stops_before_any_client_is_built(
    command: list[str], missing: str, capsys: pytest.CaptureFixture[str]
) -> None:
    outputs = {name: value for name, value in OUTPUTS.items() if name != missing}

    code = seed.main(command, read_outputs=lambda _directory: outputs, make_client=_no_client)

    assert code == 1
    assert missing in capsys.readouterr().err


def _no_outputs(_directory: Path) -> Mapping[str, object]:
    message = "reset without --yes must not read the outputs"
    raise AssertionError(message)


def _no_client(_table: object) -> "DynamoDBClient":
    message = "no client may be built here"
    raise AssertionError(message)
