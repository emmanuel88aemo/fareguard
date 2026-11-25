"""Create the AgentCore harness from the outputs of infra/main. A person runs this.

It reads the ARNs from `terraform output`, builds the configuration with
fareguard.harness.config and calls CreateHarness once. No ARN and no account
id is written in this file.

Usage:
    python scripts/create_harness.py --dry-run   # print the configuration, call nothing
    python scripts/create_harness.py             # create the harness, print its ARN
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from fareguard.harness.config import (
    MODEL_ID,
    TOOL_NAMES,
    HarnessConfig,
    HarnessConfigError,
    HarnessInputs,
    HarnessLimits,
    build_harness_config,
)

REPOSITORY = Path(__file__).resolve().parents[1]
INFRA_DIRECTORY = REPOSITORY / "infra" / "main"
SYSTEM_PROMPT_PATH = REPOSITORY / "harness" / "system_prompt.md"

# A run reads the ledger, asks or launches and answers: a dozen iterations is ample.
# The hook function has 10 seconds (infra/main/lambdas.tf); the harness waits a little
# longer, so a slow hook is reported by the function and not cut off by the harness.
LIMITS = HarnessLimits(
    max_iterations=12, max_tokens=4096, timeout_seconds=300, hook_timeout_seconds=15
)
REGION_FIELD = 3


class OutputsError(Exception):
    """The outputs of Terraform could not be read or lack a value the harness needs."""


class ControlClient(Protocol):
    """The one operation of the bedrock-agentcore-control client that is used."""

    def create_harness(self, **kwargs: object) -> Mapping[str, object]:
        """Create a harness and return the response of the API."""


def read_terraform_outputs(directory: Path) -> dict[str, object]:
    """Return the outputs of the Terraform stack in `directory`, by name.

    Raises:
        OutputsError: if Terraform fails or prints something that is not its JSON.
    """
    try:
        result = subprocess.run(
            ["terraform", "output", "-json"],  # noqa: S607 - terraform from PATH is intended
            cwd=directory,
            check=True,
            capture_output=True,
            text=True,
        )
        outputs = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        message = f"`terraform output -json` failed in {directory}: {error}"
        raise OutputsError(message) from error
    if not isinstance(outputs, dict):
        message = "`terraform output -json` did not print an object"
        raise OutputsError(message)
    return {name: entry.get("value") for name, entry in outputs.items() if isinstance(entry, dict)}


def inputs_from(outputs: Mapping[str, object], system_prompt: str) -> HarnessInputs:
    """Return the inputs of the configuration, with the ARNs taken from `outputs`.

    Raises:
        OutputsError: if an output is missing or is not text. Apply infra/main first.
    """

    def text(name: str) -> str:
        value = outputs.get(name)
        if not isinstance(value, str) or not value:
            message = f"the Terraform output {name} is missing; apply infra/main first"
            raise OutputsError(message)
        return value

    return HarnessInputs(
        harness_name=text("harness_name"),
        model_id=MODEL_ID,
        system_prompt=system_prompt,
        gateway_arn=text("gateway_arn"),
        hook_function_arn=text("hook_function_arn"),
        execution_role_arn=text("harness_execution_role_arn"),
        tool_names=TOOL_NAMES,
        limits=LIMITS,
    )


def region_of(arn: str) -> str:
    """Return the region named in `arn`, so the harness is created beside its gateway.

    Raises:
        OutputsError: if `arn` names no region.
    """
    fields = arn.split(":")
    if len(fields) <= REGION_FIELD or not fields[REGION_FIELD]:
        message = "the gateway ARN names no region"
        raise OutputsError(message)
    return fields[REGION_FIELD]


def _control_client(region: str) -> ControlClient:
    client: ControlClient = boto3.client("bedrock-agentcore-control", region_name=region)
    return client


def _create(config: HarnessConfig, client: ControlClient) -> int:
    """Call CreateHarness once and print the ARN, or the error exactly as AWS gave it."""
    try:
        response = client.create_harness(**config)
    except (ClientError, BotoCoreError) as error:
        print(f"CreateHarness failed: {error}", file=sys.stderr)
        return 1
    harness = response.get("harness")
    details = harness if isinstance(harness, Mapping) else {}
    print(f"harness ARN: {details.get('arn')}")
    print(f"status: {details.get('status')}")
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    read_outputs: Callable[[Path], Mapping[str, object]] = read_terraform_outputs,
    make_client: Callable[[str], ControlClient] = _control_client,
) -> int:
    """Create the harness, or print its configuration with --dry-run, and return an exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the configuration and call no AWS API except what `terraform output` reads",
    )
    args = parser.parse_args(argv)

    try:
        system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        inputs = inputs_from(read_outputs(INFRA_DIRECTORY), system_prompt)
        config = build_harness_config(inputs)
        region = region_of(inputs.gateway_arn)
    except (OutputsError, HarnessConfigError, OSError) as error:
        print(f"✗ {error}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(json.dumps(config, indent=2))
        return 0
    return _create(config, make_client(region))


if __name__ == "__main__":
    raise SystemExit(main())
