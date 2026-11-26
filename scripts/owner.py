"""Approve or reject the approval requests of the agent. The owner runs this, by hand.

This is the channel the agent does not have: it has no tool that approves, and
its role is not the one this script runs under. A person runs it with an admin
profile of their own, never with the role of the agent, of the tools function
or of the harness, and no workflow and no AI assistant runs it.

The table is read from `terraform output` in infra/main, so no table name and
no account id is written in this file. A decision is dated with the UTC time
of the run and cannot be changed afterwards.

Usage:
    python scripts/owner.py pending          # the requests awaiting a decision
    python scripts/owner.py approve <ref>    # approve one request
    python scripts/owner.py reject <ref>     # reject one request
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from create_harness import INFRA_DIRECTORY, OutputsError, read_terraform_outputs
from fareguard.ledger.dynamodb import DynamoLedgerStore
from fareguard.ledger.errors import LedgerError
from fareguard.ledger.store import LedgerStore
from fareguard.ops.table import LedgerTable, LedgerTableError, ledger_table
from fareguard.tools.results import usd

PENDING = "pending"
APPROVE = "approve"
REJECT = "reject"
ADMIN_NOTE = (
    "A person runs this with an admin profile, not with the role of the agent: "
    "the agent has no tool that approves."
)


def _dynamo_store(table: LedgerTable) -> LedgerStore:
    return DynamoLedgerStore(table.name, boto3.client("dynamodb", region_name=table.region))


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else None, epilog=ADMIN_NOTE
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(PENDING, help="list the approval requests awaiting a decision")
    for command, verb in ((APPROVE, "approve"), (REJECT, "reject")):
        decide = commands.add_parser(command, help=f"{verb} one pending request", epilog=ADMIN_NOTE)
        decide.add_argument("ref", help="the reference of the request, as `pending` lists it")
    return parser.parse_args(argv)


def _print_pending(store: LedgerStore) -> int:
    """Print the ref, the disc and the amount of each pending request."""
    pending = store.pending_approvals()
    if not pending:
        print("no approval request is awaiting a decision")
        return 0
    print("ref\tdisc\tamount")
    for approval in pending:
        print(f"{approval.ref}\t{approval.disc_id}\t{usd(approval.approved_usd)} USD")
    return 0


def _decide(store: LedgerStore, ref: str, approved: bool, at: datetime) -> int:
    """Write the decision through the store and print what the approval now is."""
    decided = store.decide_approval(ref, approved, at)
    print(f"{decided.status}: approval {decided.ref} for disc {decided.disc_id}")
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    read_outputs: Callable[[Path], Mapping[str, object]] = read_terraform_outputs,
    make_store: Callable[[LedgerTable], LedgerStore] = _dynamo_store,
    now: Callable[[], datetime] = _utc_now,
) -> int:
    """List the pending requests or decide one, and return an exit code."""
    args = _parse(argv)
    try:
        store = make_store(ledger_table(read_outputs(INFRA_DIRECTORY)))
        if args.command == PENDING:
            return _print_pending(store)
        return _decide(store, args.ref, args.command == APPROVE, now())
    except (OutputsError, LedgerTableError, LedgerError, ClientError, BotoCoreError) as error:
        print(f"✗ {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
