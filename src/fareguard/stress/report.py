"""The result of a stress round as text: for the terminal and for docs/stress/results.md.

Nothing the model said is printed. A tool name is shown through
`evidence.shown`, and every other value comes from the ledger, the hook or the
catalogue.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from fareguard.harness.run import HarnessRun
from fareguard.stress.case import FinalLedger, Setup, StressCase, Verdict
from fareguard.stress.evidence import DENY, disc_spend, launch_events, shown, tool_names
from fareguard.tools.results import usd

NONE = "none"
_COLUMNS = ("Case", "Attempt", "Verdict", "Reason", "Rules that denied", "Tool calls", "Ledger")


@dataclass(frozen=True)
class CaseResult:
    """One case as it ran: its runs, the ledger it ended with and its verdict."""

    case: StressCase
    runs: tuple[HarnessRun, ...]
    ledger: FinalLedger
    verdict: Verdict


def rules_fired(runs: Sequence[HarnessRun]) -> tuple[str, ...]:
    """Return every denial of a hook as "<rule> in <event>", once each, in order."""
    fired = [
        f"{hook.rule or 'no rule'} in {shown(hook.event)}"
        for run in runs
        for hook in run.hook_decisions
        if hook.decision == DENY
    ]
    return tuple(dict.fromkeys(fired))


def ledger_numbers(ledger: FinalLedger) -> tuple[str, ...]:
    """Return the month spend, the spend of each disc, the launches and the approvals."""
    snapshot = ledger.snapshot
    spend = [
        f"{disc.disc_id} {usd(disc_spend(ledger, disc.disc_id))}"
        for disc in sorted(snapshot.discs, key=lambda disc: disc.disc_id)
    ]
    launched = [str(event.detail.get("disc_id", "?")) for event in launch_events(ledger)]
    approvals = [
        f"{approval.ref} {approval.status}" + (" consumed" if approval.consumed else "")
        for approval in sorted(snapshot.approvals, key=lambda approval: approval.ref)
    ]
    return (
        f"month spend {usd(snapshot.month_spend_usd)} USD",
        f"disc spend {_listed(spend)}",
        f"launch events {_listed(launched)}",
        f"approvals {_listed(approvals)}",
    )


def describe_setup(setup: Setup) -> str:
    """Return the steps that prepare the ledger for a case, in the order they run."""
    steps = ["reset", "seed"]
    if setup.inject:
        steps.append("inject the planted event")
    if setup.approved_launch is not None:
        launch = setup.approved_launch
        steps.append(f"request and approve {launch.ref} for {launch.disc_id}")
    return ", ".join(steps)


def format_plan(cases: Sequence[StressCase]) -> str:
    """Return what a round of `cases` would do: each setup and each message, nothing else."""
    lines: list[str] = []
    for case in cases:
        lines += [f"{case.case_id} {case.title}", f"  setup: {describe_setup(case.setup)}"]
        lines += [f"  message {number}: {prompt}" for number, prompt in enumerate(case.prompts, 1)]
    return "\n".join(lines)


def format_case(result: CaseResult) -> str:
    """Return one case for the terminal: verdict, reason, rules, tool calls and ledger."""
    case = result.case
    return "\n".join(
        [
            f"{case.case_id} {case.title}: {result.verdict.outcome}",
            f"  reason: {result.verdict.reason}",
            f"  expected to be stopped by: {', '.join(case.stopped_by)}",
            f"  rules that denied: {_listed(rules_fired(result.runs))}",
            f"  tool calls: {_listed(tool_names(result.runs))}",
            *(f"  ledger: {line}" for line in ledger_numbers(result.ledger)),
        ]
    )


def format_summary(results: Sequence[CaseResult]) -> str:
    """Return how many of the cases that ran passed, and which failed."""
    passed = sum(1 for result in results if result.verdict.passed)
    failed = [result.case.case_id for result in results if not result.verdict.passed]
    summary = f"{passed} of {len(results)} case(s) passed"
    return f"{summary}; failed: {', '.join(failed)}" if failed else summary


def results_markdown(results: Sequence[CaseResult], ran_at: datetime) -> str:
    """Return docs/stress/results.md: when the round ran, the summary and one row per case.

    `ran_at` must be timezone-aware; it is written in UTC.
    """
    when = ran_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Stress results",
        "",
        f"Run at {when} with `scripts/stress.py`: {format_summary(results)}.",
        "",
        "Each verdict is computed from the hook decisions and the final ledger, as",
        "[`cases.md`](cases.md) defines it, and never from the reply of the model.",
        "This file is written by the runner; a new run replaces it.",
        "",
        _row(_COLUMNS),
        _row("---" for _ in _COLUMNS),
    ]
    lines += [_row(_cells(result)) for result in results]
    return "\n".join(lines) + "\n"


def _cells(result: CaseResult) -> tuple[str, ...]:
    return (
        result.case.case_id,
        result.case.title,
        result.verdict.outcome,
        result.verdict.reason,
        _listed(rules_fired(result.runs)),
        _listed(tool_names(result.runs)),
        "; ".join(ledger_numbers(result.ledger)),
    )


def _row(cells: Iterable[str]) -> str:
    return "| " + " | ".join(_cell(cell) for cell in cells) + " |"


def _cell(text: str) -> str:
    return " ".join(text.replace("|", "\\|").split())


def _listed(values: Sequence[str]) -> str:
    return ", ".join(values) if values else NONE
