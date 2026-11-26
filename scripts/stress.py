"""Run the stress cases A1 to A8 against the deployed agent and score them. A person runs this.

For each case it empties and seeds the ledger table, prepares what the case
needs, sends the messages of the case to the harness and reads the ledger
afterwards. The verdict comes from the hook decisions and the ledger, never
from the reply of the model: see docs/stress/cases.md. It prints each case and
a summary and writes docs/stress/results.md.

It deletes every item of the ledger table before each case, so it is refused
without --yes. A person runs it with an admin profile, never with the role of
the agent, and no workflow and no AI assistant runs it. The table is read from
`terraform output` in infra/main and the harness from the environment, so no
table name, no ARN and no account id is written in this file.

Usage:
    export FAREGUARD_HARNESS_ARN=<the ARN create_harness.py printed>
    python scripts/stress.py all --yes       # every case, in order
    python scripts/stress.py A5 --yes        # one case
    python scripts/stress.py all --dry-run   # print the setups and messages, call nothing
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import BotoCoreError, ClientError

import seed
from create_harness import INFRA_DIRECTORY, REPOSITORY, OutputsError, read_terraform_outputs
from fareguard.harness.run import (
    CLIENT_CONFIG,
    HarnessRun,
    InvalidRequestError,
    RuntimeClient,
    run_harness,
)
from fareguard.ledger.dynamodb import DynamoLedgerStore
from fareguard.ledger.errors import LedgerError
from fareguard.ledger.store import LedgerStore
from fareguard.ops.seed_data import SEED_LIMITS
from fareguard.ops.table import LedgerTable, LedgerTableError, ledger_table
from fareguard.stress.case import StressCase
from fareguard.stress.catalogue import UnknownCaseError, select
from fareguard.stress.report import (
    CaseResult,
    format_case,
    format_plan,
    format_summary,
    results_markdown,
)
from fareguard.stress.setup import StressSetupError, approve_launch, read_final_ledger

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient

HARNESS_ARN_VARIABLE = "FAREGUARD_HARNESS_ARN"
RESULTS_PATH = REPOSITORY / "docs" / "stress" / "results.md"
REGION_FIELD = 3
NOT_CONFIRMED = "the ledger table is emptied before each case; pass --yes"
NO_HARNESS = f"give --harness-arn or set {HARNESS_ARN_VARIABLE}"


class SeedFailedError(StressSetupError):
    """A command of scripts/seed.py did not succeed; it printed why."""

    def __init__(self, command: str) -> None:
        """Name the command that failed."""
        super().__init__(f"`seed.py {command}` failed, so the case was not run")


class NotStartedError(Exception):
    """The round was not started: a confirmation or the harness is missing."""


# What stops a round before it has a result: nothing was judged, so nothing is written.
_STOPS = (
    UnknownCaseError,
    NotStartedError,
    OutputsError,
    LedgerTableError,
    LedgerError,
    StressSetupError,
    InvalidRequestError,
    ClientError,
    BotoCoreError,
)


def _dynamo_client(table: LedgerTable) -> DynamoDBClient:
    return boto3.client("dynamodb", region_name=table.region)


def _runtime_client(region: str) -> RuntimeClient:
    client: RuntimeClient = boto3.client(
        "bedrock-agentcore", region_name=region, config=CLIENT_CONFIG
    )
    return client


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Dependencies:
    """What the runner reaches outside itself. A test replaces each one."""

    read_outputs: Callable[[Path], Mapping[str, object]] = read_terraform_outputs
    make_dynamo: Callable[[LedgerTable], DynamoDBClient] = _dynamo_client
    make_runtime: Callable[[str], RuntimeClient] = _runtime_client
    now: Callable[[], datetime] = _utc_now
    results_path: Path = RESULTS_PATH


@dataclass(frozen=True)
class _Round:
    """The ledger table and the harness of one round, as every case uses them."""

    outputs: Mapping[str, object]
    dynamo: DynamoDBClient
    store: LedgerStore
    runtime: RuntimeClient
    harness_arn: str
    now: Callable[[], datetime]


def _region_of(arn: str) -> str | None:
    fields = arn.split(":")
    return fields[REGION_FIELD] if len(fields) > REGION_FIELD and fields[REGION_FIELD] else None


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("case", help="the case to run, A1 to A8, or `all`")
    parser.add_argument(
        "--harness-arn",
        default=os.environ.get(HARNESS_ARN_VARIABLE, ""),
        help=f"ARN of the harness; defaults to the environment variable {HARNESS_ARN_VARIABLE}",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="required: confirm that the ledger table is emptied before each case",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the setup and the messages of each case and call nothing",
    )
    return parser.parse_args(argv)


def _seed(command: Sequence[str], round_: _Round) -> None:
    """Run one command of scripts/seed.py against the table of the round."""
    code = seed.main(
        command,
        read_outputs=lambda _directory: round_.outputs,
        make_client=lambda _table: round_.dynamo,
        now=round_.now,
    )
    if code != 0:
        raise SeedFailedError(command[0])


def _set_up(case: StressCase, round_: _Round) -> None:
    """Empty and seed the ledger, then add what the case needs."""
    _seed(["reset", "--yes"], round_)
    _seed(["seed"], round_)
    if case.setup.inject:
        _seed(["inject"], round_)
    if case.setup.approved_launch is not None:
        launch = case.setup.approved_launch
        approve_launch(round_.store, launch, SEED_LIMITS, round_.now())
        print(f"approved {launch.ref} for {launch.disc_id}")


def _invoke(prompt: str, round_: _Round) -> HarnessRun:
    """Send one message in a session of its own and print how the call ended."""
    run = run_harness(round_.runtime, round_.harness_arn, prompt)
    print(f"invoked, runtime session id: {run.session_id}")
    if run.failure is not None:
        print(f"  InvokeHarness failed: {run.failure}", file=sys.stderr)
    for error in run.errors:
        print(f"  error: {error}", file=sys.stderr)
    return run


def _run_case(case: StressCase, round_: _Round) -> CaseResult:
    print(f"\n--- {case.case_id} {case.title}")
    _set_up(case, round_)
    runs = tuple(_invoke(prompt, round_) for prompt in case.prompts)
    ledger = read_final_ledger(round_.store, round_.now())
    result = CaseResult(case, runs, ledger, case.verdict(runs, ledger))
    print(format_case(result))
    return result


def _run_round(
    cases: Sequence[StressCase], harness_arn: str, region: str, dependencies: Dependencies
) -> list[CaseResult]:
    outputs = dependencies.read_outputs(INFRA_DIRECTORY)
    table = ledger_table(outputs)
    dynamo = dependencies.make_dynamo(table)
    round_ = _Round(
        outputs=outputs,
        dynamo=dynamo,
        store=DynamoLedgerStore(table.name, dynamo),
        runtime=dependencies.make_runtime(region),
        harness_arn=harness_arn,
        now=dependencies.now,
    )
    return [_run_case(case, round_) for case in cases]


def _region(args: argparse.Namespace) -> str:
    """Return the region of the harness, once the round is confirmed and has a harness.

    Raises:
        NotStartedError: if --yes is missing or the ARN of the harness names no region.
    """
    if not args.yes:
        raise NotStartedError(NOT_CONFIRMED)
    region = _region_of(args.harness_arn)
    if region is None:
        raise NotStartedError(NO_HARNESS)
    return region


def _finish(results: Sequence[CaseResult], started: datetime, results_path: Path) -> int:
    """Print the summary, write the results file and return the exit code of the round."""
    print(f"\n{format_summary(results)}")
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(results_markdown(results, started), encoding="utf-8")
    print(f"wrote {results_path}")
    return 0 if all(result.verdict.passed for result in results) else 1


def main(argv: Sequence[str] | None = None, dependencies: Dependencies | None = None) -> int:
    """Run the requested cases, print and write the results and return an exit code.

    The exit code is 0 only when every case that ran passed. A round that
    cannot be set up or read stops with 1 and writes no results file.
    """
    args = _parse(argv)
    uses = Dependencies() if dependencies is None else dependencies
    try:
        cases = select(args.case)
        if args.dry_run:
            print(format_plan(cases))
            return 0
        region = _region(args)
        started = uses.now()
        results = _run_round(cases, args.harness_arn, region, uses)
    except _STOPS as error:
        print(f"✗ {error}", file=sys.stderr)
        return 1
    return _finish(results, started, uses.results_path)


if __name__ == "__main__":
    raise SystemExit(main())
