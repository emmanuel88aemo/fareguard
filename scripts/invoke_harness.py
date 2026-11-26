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
import sys
from collections.abc import Callable, Sequence

import boto3
from botocore.exceptions import ClientError

from fareguard.harness.run import (
    CLIENT_CONFIG,
    HarnessRun,
    InvalidRequestError,
    RuntimeClient,
    build_request,
    format_run,
    new_session_id,
    run_harness,
)

HARNESS_ARN_VARIABLE = "FAREGUARD_HARNESS_ARN"
REGION_FIELD = 3


def _runtime_client(region: str) -> RuntimeClient:
    client: RuntimeClient = boto3.client(
        "bedrock-agentcore", region_name=region, config=CLIENT_CONFIG
    )
    return client


def _region_of(arn: str) -> str | None:
    fields = arn.split(":")
    return fields[REGION_FIELD] if len(fields) > REGION_FIELD and fields[REGION_FIELD] else None


def _report(run: HarnessRun) -> int:
    """Print the transcript and any error exactly as AWS gave it, and return the exit code."""
    # What arrived before a failure is still printed.
    print(format_run(run))
    if run.failure is not None:
        print(f"InvokeHarness failed: {run.failure}", file=sys.stderr)
        if isinstance(run.failure, ClientError):
            print(json.dumps(run.failure.response, indent=2, default=str), file=sys.stderr)
        return 1
    return 1 if run.errors else 0


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


def main(
    argv: Sequence[str] | None = None,
    *,
    make_client: Callable[[str], RuntimeClient] = _runtime_client,
) -> int:
    """Invoke the harness with one message, print the transcript and return an exit code."""
    args = _parse(argv)
    session_id = args.session_id or new_session_id()
    region = _region_of(args.harness_arn)
    if region is None:
        print(f"✗ give --harness-arn or set {HARNESS_ARN_VARIABLE}", file=sys.stderr)
        return 1
    try:
        request = build_request(args.harness_arn, session_id, args.message)
    except InvalidRequestError as error:
        print(f"✗ {error}", file=sys.stderr)
        return 1

    print(f"runtime session id: {session_id}")
    if args.dry_run:
        print(json.dumps(request, indent=2))
        return 0
    return _report(run_harness(make_client(region), args.harness_arn, args.message, session_id))


if __name__ == "__main__":
    raise SystemExit(main())
