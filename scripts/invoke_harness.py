"""Send one message to the AgentCore harness and print what happened. A person runs this.

It prints the model's reply, the tool calls, what each hook decided and why
each message stopped. An error, such as a model the harness rejects, is
printed exactly as AWS returned it. Nothing of the harness is overridden: the
call uses the model, the prompt, the tools and the limits it was created with.

Usage:
    export FAREGUARD_HARNESS_ARN=<the ARN create_harness.py printed>
    python scripts/invoke_harness.py "What is queued?"
    python scripts/invoke_harness.py --session-id <id of an earlier run> "And now?"
    python scripts/invoke_harness.py --dry-run "What is queued?"   # call nothing
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from fareguard.harness.stream import format_transcript, read_stream

HARNESS_ARN_VARIABLE = "FAREGUARD_HARNESS_ARN"
# InvokeHarness requires a runtime session id of 33 to 100 characters.
SESSION_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{32,99}$")
REGION_FIELD = 3

# One attempt: a retry would send the message, and perhaps a launch, a second time.
# The read timeout is longer than the 300 seconds an invocation may take.
CLIENT_CONFIG = Config(read_timeout=330, retries={"total_max_attempts": 1})


class RuntimeClient(Protocol):
    """The one operation of the bedrock-agentcore client that is used."""

    def invoke_harness(self, **kwargs: object) -> Mapping[str, object]:
        """Invoke a harness and return the response of the API, which holds the stream."""


def new_session_id() -> str:
    """Return a new runtime session id: 42 characters, within the 33 to 100 required."""
    return f"fareguard-{uuid.uuid4().hex}"


def build_request(harness_arn: str, session_id: str, message: str) -> dict[str, object]:
    """Return the arguments of InvokeHarness for one user message, with no override."""
    return {
        "harnessArn": harness_arn,
        "runtimeSessionId": session_id,
        "messages": [{"role": "user", "content": [{"text": message}]}],
    }


def _runtime_client(region: str) -> RuntimeClient:
    client: RuntimeClient = boto3.client(
        "bedrock-agentcore", region_name=region, config=CLIENT_CONFIG
    )
    return client


def _region_of(arn: str) -> str | None:
    fields = arn.split(":")
    return fields[REGION_FIELD] if len(fields) > REGION_FIELD and fields[REGION_FIELD] else None


def _invoke(request: Mapping[str, object], client: RuntimeClient) -> int:
    """Call InvokeHarness once, print the transcript and any error exactly as AWS gave it."""
    events: list[object] = []
    failure: Exception | None = None
    try:
        stream = client.invoke_harness(**request).get("stream")
        events.extend(stream if isinstance(stream, Iterable) else ())
    except (ClientError, BotoCoreError) as error:
        failure = error

    # What arrived before a failure is still printed.
    transcript = read_stream(events)
    print(format_transcript(transcript))
    if failure is not None:
        print(f"InvokeHarness failed: {failure}", file=sys.stderr)
        if isinstance(failure, ClientError):
            print(json.dumps(failure.response, indent=2, default=str), file=sys.stderr)
        return 1
    return 1 if transcript.errors else 0


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("message", help="the message to send to the agent")
    parser.add_argument(
        "--harness-arn",
        default=os.environ.get(HARNESS_ARN_VARIABLE, ""),
        help=f"ARN of the harness; defaults to the environment variable {HARNESS_ARN_VARIABLE}",
    )
    parser.add_argument(
        "--session-id",
        help="runtime session id of 33 to 100 characters, to continue a session; "
        "a new one is generated when it is not given",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the request and call no AWS API"
    )
    return parser.parse_args(argv)


def _problem(region: str | None, message: str, session_id: str) -> str | None:
    """Return what is wrong with the arguments, or None when the request can be sent."""
    if region is None:
        return f"give --harness-arn or set {HARNESS_ARN_VARIABLE}"
    if not message.strip():
        return "the message must not be empty"
    if SESSION_ID.fullmatch(session_id) is None:
        return "the session id must be 33 to 100 letters, digits, - or _"
    return None


def main(
    argv: Sequence[str] | None = None,
    *,
    make_client: Callable[[str], RuntimeClient] = _runtime_client,
) -> int:
    """Invoke the harness with one message, print the transcript and return an exit code."""
    args = _parse(argv)
    session_id = args.session_id or new_session_id()
    region = _region_of(args.harness_arn)
    problem = _problem(region, args.message, session_id)
    if region is None or problem is not None:
        print(f"✗ {problem}", file=sys.stderr)
        return 1

    request = build_request(args.harness_arn, session_id, args.message)
    print(f"runtime session id: {session_id}")
    if args.dry_run:
        print(json.dumps(request, indent=2))
        return 0
    return _invoke(request, make_client(region))


if __name__ == "__main__":
    raise SystemExit(main())
