"""Put the ledger table in a known state for the stress tests. A person runs this, by hand.

`seed` writes the discs and the planted event of fareguard.ops.seed_data,
`reset` deletes every item of the table and `show` prints the ledger as the
read_ledger tool presents it. `seed` and `reset` write the table directly,
outside the ledger store, which has no operation that adds a disc or deletes
anything: see docs/decisions/0009-seed-and-reset-outside-the-store.md.

A person runs it with an admin profile, never with the role of the agent. The
table is read from `terraform output` in infra/main, so no table name and no
account id is written in this file.

Usage:
    python scripts/seed.py reset --yes   # delete every item; refused without --yes
    python scripts/seed.py seed          # write the discs and the planted event
    python scripts/seed.py show          # print discs, month spend and recent events
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from create_harness import INFRA_DIRECTORY, OutputsError, read_terraform_outputs
from fareguard.ledger import items
from fareguard.ledger.dynamodb import DynamoLedgerStore
from fareguard.ledger.errors import LedgerError
from fareguard.ops.seed_data import SEED_DISCS, SEED_LIMITS, disc_item, planted_event
from fareguard.ops.table import LedgerTable, LedgerTableError, ledger_table
from fareguard.tools.read import read_ledger

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient

SEED = "seed"
RESET = "reset"
SHOW = "show"
_IF_NEW = "attribute_not_exists(pk)"


def _dynamo_client(table: LedgerTable) -> DynamoDBClient:
    return boto3.client("dynamodb", region_name=table.region)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(SEED, help="write the fixture discs and the planted event")
    reset = commands.add_parser(RESET, help="delete every item of the ledger table")
    reset.add_argument("--yes", action="store_true", help="required: confirm the deletion")
    commands.add_parser(SHOW, help="print the ledger as the read_ledger tool presents it")
    return parser.parse_args(argv)


def _seed(client: DynamoDBClient, table: str, at: datetime) -> int:
    """Write each disc if it is new, then the planted event, and print what was written.

    A disc that exists is never replaced, because that would erase its spend
    and the mark of its pending request. The run stops there: reset first.
    """
    for disc in SEED_DISCS:
        try:
            client.put_item(TableName=table, Item=disc_item(disc), ConditionExpression=_IF_NEW)
        except client.exceptions.ConditionalCheckFailedException:
            print(
                f"✗ disc {disc.disc_id} is already in {table}; nothing more was written. "
                "Run `reset --yes` first.",
                file=sys.stderr,
            )
            return 1
        print(f"wrote disc {disc.disc_id}: {disc.duration_seconds // 60} minutes")
    event = planted_event(at)
    # A plain PutItem with no condition: the event is data, as any untrusted event would be.
    client.put_item(TableName=table, Item=items.event_item(event))
    print(f"wrote event {event.event_id} ({event.type}): {json.dumps(dict(event.detail))}")
    return 0


def _reset(client: DynamoDBClient, table: str) -> int:
    """Delete every item of the table and print how many there were."""
    deleted = 0
    pages = client.get_paginator("scan").paginate(
        TableName=table, ConsistentRead=True, ProjectionExpression="pk, sk"
    )
    for page in pages:
        for key in page["Items"]:
            client.delete_item(TableName=table, Key=key)
            deleted += 1
    print(f"deleted {deleted} item(s) from {table}")
    return 0


def _show(client: DynamoDBClient, table: str, at: datetime) -> int:
    """Print what read_ledger returns for this table. The remaining spend uses SEED_LIMITS."""
    view = read_ledger(DynamoLedgerStore(table, client), SEED_LIMITS, at)
    print(json.dumps(view, indent=2))
    return 1 if "refused" in view else 0


def _run(command: str, client: DynamoDBClient, table: str, at: datetime) -> int:
    if command == SEED:
        return _seed(client, table, at)
    if command == RESET:
        return _reset(client, table)
    return _show(client, table, at)


def main(
    argv: Sequence[str] | None = None,
    *,
    read_outputs: Callable[[Path], Mapping[str, object]] = read_terraform_outputs,
    make_client: Callable[[LedgerTable], DynamoDBClient] = _dynamo_client,
    now: Callable[[], datetime] = _utc_now,
) -> int:
    """Seed, reset or show the ledger table and return an exit code."""
    args = _parse(argv)
    if args.command == RESET and not args.yes:
        print("✗ reset deletes every item of the ledger table; pass --yes", file=sys.stderr)
        return 1
    try:
        table = ledger_table(read_outputs(INFRA_DIRECTORY))
        return _run(args.command, make_client(table), table.name, now())
    except (OutputsError, LedgerTableError, LedgerError, ClientError, BotoCoreError) as error:
        print(f"✗ {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
