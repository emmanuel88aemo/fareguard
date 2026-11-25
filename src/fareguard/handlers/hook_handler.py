"""The Lambda entry point of the hook the harness invokes on its lifecycle events.

It gathers what a decision needs and passes the event on: a "before_tool_call"
goes to `decide` with the ledger, the limits and the clock, and every other
event goes to `screen` with the guardrail. It holds no rule: whatever fails
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
from fareguard.handlers.config import load_config, load_guardrail_config
from fareguard.hook.bedrock_guardrail import CLIENT_CONFIG, BedrockGuardrail
from fareguard.hook.decide import (
    BEFORE_TOOL_CALL,
    HookAnswer,
    HookRecord,
    HookResult,
    decide,
    undecided,
)
from fareguard.hook.guardrail import Guardrail
from fareguard.hook.screen import ScreenRecord, ScreenResult, read_event_name, screen
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


@functools.cache
def _guardrail() -> Guardrail:
    """Build the bedrock-runtime client and the guardrail once per container.

    Apart from `_dependencies`, so that a tool call is decided without the
    guardrail and a text is screened without the ledger. A failure is not
    cached.

    Raises:
        ConfigError: if an environment variable is missing or invalid.
    """
    config = load_guardrail_config(os.environ)
    return BedrockGuardrail(
        config.guardrail_id,
        config.guardrail_version,
        boto3.client("bedrock-runtime", config=CLIENT_CONFIG),
    )


class _ContainerGuardrail:
    """The guardrail of this container, built when the first text has to be checked."""

    def blocks(self, text: str) -> bool:
        """Return whether the guardrail blocks `text`.

        Raises:
            ConfigError: if the guardrail cannot be built from the environment.
        """
        return _guardrail().blocks(text)


def _answer(event: object) -> HookResult | ScreenResult:
    if read_event_name(event) == BEFORE_TOOL_CALL:
        dependencies = _dependencies()
        return decide(event, dependencies.store, dependencies.limits, datetime.now(UTC))
    return screen(event, _ContainerGuardrail())


def _log(record: HookRecord | ScreenRecord) -> None:
    """Write `record` as one line of JSON to standard output, which Lambda sends to the log."""
    sys.stdout.write(json.dumps(record) + "\n")


def lambda_handler(event: object, _context: object) -> HookAnswer:
    """Answer one hook event with allow or deny, and log the decision as one JSON line.

    Never raises: an error in the configuration, in building a client or
    anywhere else is answered with a denial under R5.
    """
    result: HookResult | ScreenResult
    try:
        result = _answer(event)
    # The handler boundary: the harness must receive a denial, never an error.
    except Exception as error:  # noqa: BLE001
        result = undecided(event, error)
    _log(result.record)
    return result.answer
