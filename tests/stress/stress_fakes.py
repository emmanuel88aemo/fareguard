"""Fake runs and fake ledgers for the tests of the stress package."""

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal

from fareguard.gate.models import Approval, LedgerSnapshot
from fareguard.harness.run import HarnessRun, HookVerdict
from fareguard.harness.stream import ToolCall
from fareguard.hook.decide import DENIAL_REASONS
from fareguard.ledger.store import Launch, LedgerEvent
from fareguard.ops.seed_data import SEED_DISCS
from fareguard.stress.case import FinalLedger

NOW = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
INVOKED = HookVerdict("before_invocation", "fareguard_hook", "allow", None, "allowed")


def denied(rule: str, event: str = "before_tool_call") -> HookVerdict:
    """A hook decision that denies with the fixed sentence of `rule`."""
    reason = DENIAL_REASONS[rule]  # type: ignore[index]  # a test passes a rule id as plain text
    return HookVerdict(event, "fareguard_hook", "deny", rule, reason)


def allowed(event: str = "before_tool_call") -> HookVerdict:
    """A hook decision that allows."""
    return HookVerdict(event, "fareguard_hook", "allow", None, "allowed")


def run(*hooks: HookVerdict, tools: tuple[str, ...] = (), reply: str = "") -> HarnessRun:
    """A run that reached the agent, with the tool calls `tools` and the decisions `hooks`."""
    calls = tuple(ToolCall(name, f"t{number}", "{}") for number, name in enumerate(tools))
    return HarnessRun("s" * 40, reply, calls, (INVOKED, *hooks), ("end_turn",), (), None)


def unanswered() -> HarnessRun:
    """A run that shows no hook decision: the call failed before the agent was reached."""
    return HarnessRun("s" * 40, "", (), (), (), (), None)


def launched(disc_id: str, ref: str = "apr-1") -> LedgerEvent:
    """The event the store writes for a launch of `disc_id` under `ref`."""
    return Launch(disc_id, ref, Decimal("0.60"), NOW).event()


def approval(ref: str, disc_id: str, status: str, consumed: bool = False) -> Approval:
    """An approval of 0.60 USD to launch `disc_id`."""
    return Approval(ref, "launch_job", disc_id, Decimal("0.60"), status, consumed)


def ledger(
    spend: Mapping[str, str] | None = None,
    events: tuple[LedgerEvent, ...] = (),
    approvals: tuple[Approval, ...] = (),
    month: str | None = None,
) -> FinalLedger:
    """A final ledger of the seeded discs. The month spend is the sum of `spend` by default."""
    disc_spend = {disc_id: Decimal(amount) for disc_id, amount in (spend or {}).items()}
    month_usd = sum(disc_spend.values(), Decimal("0.00")) if month is None else Decimal(month)
    return FinalLedger(LedgerSnapshot(SEED_DISCS, approvals, month_usd, disc_spend), events)
