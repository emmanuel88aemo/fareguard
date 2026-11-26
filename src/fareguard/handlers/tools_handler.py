"""The Lambda entry point of the agent's tools, invoked through the AgentCore Gateway.

It gathers what a tool needs (the environment, a DynamoDB client, the clock
and a source of approval refs), reads the tool name and calls `dispatch`. It
holds no rule and no tool: whatever fails here is answered with a refusal
under R5, never with an error the agent could read.
"""

import functools
import json
import os
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypedDict

import boto3

from fareguard.gate.models import Limits
from fareguard.handlers.config import load_config
from fareguard.hook.decide import MAX_RAW_TOOL_LENGTH
from fareguard.ledger.dynamodb import DynamoLedgerStore
from fareguard.ledger.store import LedgerStore
from fareguard.tool_names import normalise_tool_name
from fareguard.tools.dispatch import ToolContext, ToolResult, dispatch
from fareguard.tools.results import Detailed, refusal

TOOL_NAME_KEY = "bedrockAgentCoreToolName"


class ToolRecord(TypedDict):
    """One call as it is logged. It is never returned to the agent.

    `raw_tool` is the tool name exactly as it arrived, cut to
    MAX_RAW_TOOL_LENGTH characters, and `tool` is the same without its gateway
    target. `rule` is the rule of a refusal, or None. `detail` is the reason
    of the gate or of the store, or None; it may quote a disc id or an approval
    ref of the call, but only one with the strict shape of an identifier, and
    no other argument text is recorded. `error` is the class name of an
    exception that forced the refusal, or None.
    """

    tool: str | None
    raw_tool: str | None
    rule: str | None
    detail: str | None
    error: str | None


@dataclass(frozen=True)
class _Dependencies:
    store: LedgerStore
    limits: Limits


@functools.cache
def _dependencies() -> _Dependencies:
    """Build the client, the store and the limits once per container.

    A failure is not cached, so a container with a broken configuration refuses
    every call and tries again on the next one.

    Raises:
        ConfigError: if an environment variable is missing or invalid.
    """
    config = load_config(os.environ)
    return _Dependencies(
        store=DynamoLedgerStore(config.table_name, boto3.client("dynamodb")),
        limits=config.limits,
    )


def _read_tool_name(context: object) -> str | None:
    """Return the tool name as the gateway sent it, or None when there is none."""
    # ASSUMPTION, to confirm at deploy time: the gateway passes the tool name in the Lambda
    # context, as context.client_context.custom["bedrockAgentCoreToolName"], and the event
    # holds nothing but the tool's arguments. This function is the only place that knows
    # where the name is; `fareguard.tool_names` is the only place that knows its prefix.
    client_context = getattr(context, "client_context", None)
    custom = getattr(client_context, "custom", None)
    name = custom.get(TOOL_NAME_KEY) if isinstance(custom, Mapping) else None
    return name if isinstance(name, str) else None


def _new_approval_ref() -> str:
    """Return a ref nobody chose: "apr-" and 32 random hexadecimal digits."""
    return f"apr-{uuid.uuid4().hex}"


def _run(event: object, raw_tool: str | None) -> Detailed[ToolResult]:
    dependencies = _dependencies()
    tool = None if raw_tool is None else normalise_tool_name(raw_tool)
    context = ToolContext(
        dependencies.store, dependencies.limits, datetime.now(UTC), _new_approval_ref
    )
    return dispatch(tool, event, context)


def _log(raw_tool: str | None, outcome: Detailed[ToolResult], error: str | None) -> None:
    """Write one line of JSON to standard output, which Lambda sends to the log."""
    cut = None if raw_tool is None else raw_tool[:MAX_RAW_TOOL_LENGTH]
    rule = outcome.result.get("rule")
    record: ToolRecord = {
        "tool": None if cut is None else normalise_tool_name(cut),
        "raw_tool": cut,
        "rule": rule if isinstance(rule, str) else None,
        "detail": outcome.detail,
        "error": error,
    }
    sys.stdout.write(json.dumps(record) + "\n")


def lambda_handler(event: object, context: object) -> ToolResult:
    """Carry out the tool call whose arguments are `event`, and log it as one JSON line.

    Never raises: a missing tool name, an error in the configuration, in
    building the client or in the ledger is answered with a refusal under R5.
    The result holds a fixed reason; the detail goes to the log only.
    """
    raw_tool, error = None, None
    try:
        raw_tool = _read_tool_name(context)
        outcome = _run(event, raw_tool)
    # The handler boundary: the agent must receive a refusal, never a stack trace.
    except Exception as failure:  # noqa: BLE001
        outcome, error = Detailed(refusal("R5"), None), type(failure).__name__
    _log(raw_tool, outcome, error)
    return outcome.result
