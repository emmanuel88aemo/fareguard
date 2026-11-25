"""The Lambda entry point of the hook the harness invokes before every tool call.

It gathers what the decision needs (the environment, a DynamoDB client and the
clock), calls `decide` and returns its answer. It holds no rule: whatever fails
here is denied with R5.
"""

import functools
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

import boto3

from fareguard.gate.models import Limits
from fareguard.handlers.config import load_config
from fareguard.hook.decide import HookAnswer, HookRecord, decide, undecided
from fareguard.ledger.dynamodb import DynamoLedgerStore
from fareguard.ledger.store import LedgerStore


@dataclass(frozen=True)
class _Dependencies:
    store: LedgerStore
    limits: Limits


@functools.cache
def _dependencies() -> _Dependencies:
    """Build the client, the store and the limits once per container.

    A failure is not cached, so a container with a broken configuration denies
    every call and tries again on the next one.

    Raises:
        ConfigError: if an environment variable is missing or invalid.
    """
    config = load_config(os.environ)
    return _Dependencies(
        store=DynamoLedgerStore(config.table_name, boto3.client("dynamodb")),
        limits=config.limits,
    )


def _log(record: HookRecord) -> None:
    """Write `record` as one line of JSON to standard output, which Lambda sends to the log."""
    sys.stdout.write(json.dumps(record) + "\n")


def lambda_handler(event: object, _context: object) -> HookAnswer:
    """Answer one hook event with allow or deny, and log the decision as one JSON line.

    Never raises: an error in the configuration, in building the client or
    anywhere else is answered with a denial under R5.
    """
    try:
        dependencies = _dependencies()
        result = decide(event, dependencies.store, dependencies.limits, datetime.now(UTC))
    # The handler boundary: the harness must receive a denial, never an error.
    except Exception as error:  # noqa: BLE001
        result = undecided(event, error)
    _log(result.record)
    return result.answer
