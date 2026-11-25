"""Fixtures shared by the ledger tests: one seeded store per implementation."""

import os
from collections.abc import Callable, Iterable, Iterator, Mapping
from decimal import Decimal
from typing import TYPE_CHECKING

import boto3
import pytest
from moto import mock_aws

from fareguard.gate.models import Approval, Disc
from fareguard.ledger.dynamodb import DynamoLedgerStore
from fareguard.ledger.memory import InMemoryLedgerStore
from fareguard.ledger.store import LedgerStore

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient

TABLE = "fareguard-test-ledger"
RUN_AWS_TESTS = "FAREGUARD_RUN_AWS_TESTS"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip every test marked "aws" unless FAREGUARD_RUN_AWS_TESTS is exactly "1".

    A skipped test sets up no fixture, so the default run creates no client.
    """
    if os.environ.get(RUN_AWS_TESTS) == "1":
        return
    skip = pytest.mark.skip(reason=f"uses real AWS; set {RUN_AWS_TESTS}=1 to run it")
    for item in items:
        if item.get_closest_marker("aws") is not None:
            item.add_marker(skip)


@pytest.fixture
def table_name() -> str:
    return TABLE


@pytest.fixture
def dynamodb_client(monkeypatch: pytest.MonkeyPatch) -> Iterator["DynamoDBClient"]:
    """A client for an empty ledger table in moto. Fake credentials keep it away from AWS."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
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
        yield client


def _make_memory_store(
    discs: Iterable[Disc] = (),
    approvals: Iterable[Approval] = (),
    disc_spend_usd: Mapping[str, Decimal] | None = None,
    month_spend_usd: Mapping[str, Decimal] | None = None,
) -> LedgerStore:
    return InMemoryLedgerStore(discs, approvals, disc_spend_usd, month_spend_usd)


def _dynamodb_factory(client: "DynamoDBClient") -> Callable[..., LedgerStore]:
    """Return a factory that writes the seed as raw items, independently of the store's code."""

    def put(pk: str, sk: str, **attributes: Mapping[str, object]) -> None:
        client.put_item(TableName=TABLE, Item={"pk": {"S": pk}, "sk": {"S": sk}, **attributes})

    def make(
        discs: Iterable[Disc] = (),
        approvals: Iterable[Approval] = (),
        disc_spend_usd: Mapping[str, Decimal] | None = None,
        month_spend_usd: Mapping[str, Decimal] | None = None,
    ) -> LedgerStore:
        approvals = list(approvals)
        pending = {a.disc_id: a.ref for a in approvals if a.status == "pending"}
        for disc in discs:
            extra: dict[str, Mapping[str, object]] = {}
            if disc.disc_id in (disc_spend_usd or {}):
                extra["spent_usd"] = {"N": str((disc_spend_usd or {})[disc.disc_id])}
            if disc.disc_id in pending:
                extra["pending_approval_ref"] = {"S": pending[disc.disc_id]}
            put("DISC", disc.disc_id, duration_seconds={"N": str(disc.duration_seconds)}, **extra)
        for approval in approvals:
            put(
                "APPROVAL",
                approval.ref,
                action={"S": approval.action},
                disc_id={"S": approval.disc_id},
                approved_usd={"N": str(approval.approved_usd)},
                status={"S": approval.status},
                consumed={"BOOL": approval.consumed},
                requested_at={"S": "2026-11-24T09:00:00+00:00"},
            )
        for month, spent_usd in (month_spend_usd or {}).items():
            put("SPEND", month, spent_usd={"N": str(spent_usd)})
        return DynamoLedgerStore(TABLE, client)

    return make


@pytest.fixture(params=["memory", "dynamodb"])
def make_store(request: pytest.FixtureRequest) -> Callable[..., LedgerStore]:
    """Return a factory that builds a seeded store; the contract suite runs once per param."""
    if request.param == "memory":
        return _make_memory_store
    return _dynamodb_factory(request.getfixturevalue("dynamodb_client"))
