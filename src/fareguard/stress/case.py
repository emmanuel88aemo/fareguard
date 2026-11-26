"""A stress case, the ledger it ends with and the verdict on it.

A verdict is decided from what the hooks answered and from what the ledger
holds, never from what the model said: see
docs/decisions/0012-stress-verdicts-from-the-ledger-and-the-hooks.md.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from fareguard.gate.models import LedgerSnapshot, RuleId
from fareguard.harness.run import HarnessRun
from fareguard.ledger.store import LedgerEvent


@dataclass(frozen=True)
class FinalLedger:
    """The ledger after the last invocation of a case: its snapshot and every event."""

    snapshot: LedgerSnapshot
    events: tuple[LedgerEvent, ...]


@dataclass(frozen=True)
class Verdict:
    """Whether the rules held in one case, and the observations that say so."""

    passed: bool
    reason: str

    @property
    def outcome(self) -> str:
        """The verdict as it is reported: "PASS" or "FAIL"."""
        return "PASS" if self.passed else "FAIL"


@dataclass(frozen=True)
class ApprovedLaunch:
    """An approval the owner grants before the agent is invoked: one disc, under one ref."""

    disc_id: str
    ref: str


@dataclass(frozen=True)
class Setup:
    """What a case needs on top of an emptied and seeded ledger.

    `inject` adds the planted event. `approved_launch` is requested and
    approved through the store, for the estimated cost of its disc.
    """

    inject: bool = False
    approved_launch: ApprovedLaunch | None = None


type Judge = Callable[[Sequence[HarnessRun], FinalLedger], Verdict]


@dataclass(frozen=True)
class StressCase:
    """One adversarial attempt: its setup, the messages sent and the function that judges it.

    `stopped_by` names the rules expected to stop the attempt. It documents the
    case and is not part of the verdict. `judge` is pure and expects one run
    per prompt, in order; call `verdict`, which checks that first.
    """

    case_id: str
    title: str
    stopped_by: tuple[RuleId, ...]
    setup: Setup
    prompts: tuple[str, ...]
    judge: Judge

    def verdict(self, runs: Sequence[HarnessRun], ledger: FinalLedger) -> Verdict:
        """Return the verdict of the case, given one run per prompt and the final ledger.

        A case fails without being judged when a run is missing or shows no
        hook decision. The hook answers every invocation, so a run without a
        decision never reached the agent, and an untouched ledger would then
        pass most cases although nothing was attempted.
        """
        if len(runs) != len(self.prompts):
            return Verdict(False, f"expected {len(self.prompts)} invocation(s) and got {len(runs)}")
        silent = [str(number) for number, run in enumerate(runs, 1) if not run.hook_decisions]
        if silent:
            return Verdict(
                False,
                f"invocation {', '.join(silent)} shows no hook decision: the message did not "
                "reach the agent, so nothing was tested",
            )
        return self.judge(runs, ledger)
