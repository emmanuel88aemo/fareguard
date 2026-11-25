"""Read the event stream of InvokeHarness into a transcript a person can check.

The transcript keeps what shows whether the rules held: what the model said,
which tools it called and with what input, what each hook decided, why each
message stopped and every error, word for word.
"""

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

ERROR_EVENTS: tuple[str, ...] = (
    "runtimeClientError",
    "validationException",
    "internalServerException",
)


@dataclass(frozen=True)
class ToolCall:
    """One tool call the model asked for. `input` is the JSON text as the model wrote it."""

    name: str
    tool_use_id: str
    input: str


@dataclass(frozen=True)
class HookDecision:
    """What one hook answered. `decision` is None for a target that returns none."""

    name: str
    event: str
    decision: str | None
    reason: str | None


@dataclass(frozen=True)
class Transcript:
    """Everything read from one response stream, in the order it arrived."""

    reply: str
    tool_calls: tuple[ToolCall, ...]
    hook_decisions: tuple[HookDecision, ...]
    stop_reasons: tuple[str, ...]
    errors: tuple[str, ...]


@dataclass
class _OpenCall:
    name: str
    tool_use_id: str
    parts: list[str] = field(default_factory=list)


@dataclass
class _Collector:
    """What has been read so far. Tool input arrives in pieces, keyed by the block index."""

    texts: list[str] = field(default_factory=list)
    open_calls: dict[object, _OpenCall] = field(default_factory=dict)
    tool_calls: list[ToolCall] = field(default_factory=list)
    hook_decisions: list[HookDecision] = field(default_factory=list)
    stop_reasons: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add(self, key: str, payload: Mapping[str, object]) -> None:
        if key in ERROR_EVENTS:
            # The whole payload, unchanged: a rejected model or request must be readable.
            self.errors.append(f"{key}: {json.dumps(payload, default=str)}")
        elif key == "contentBlockStart":
            self._start(payload)
        elif key == "contentBlockDelta":
            self._delta(payload)
        elif key == "contentBlockStop":
            self._close(payload.get("contentBlockIndex"))
        elif key == "messageStop":
            self.stop_reasons.append(_text(payload.get("stopReason")) or "unknown")
        elif key == "hookEvent":
            self.hook_decisions.append(_hook_decision(payload))

    def _start(self, payload: Mapping[str, object]) -> None:
        tool_use = _mapping(_mapping(payload.get("start")).get("toolUse"))
        if tool_use:
            index = payload.get("contentBlockIndex")
            self._close(index)
            self.open_calls[index] = _OpenCall(
                _text(tool_use.get("name")) or "unknown",
                _text(tool_use.get("toolUseId")) or "unknown",
            )

    def _delta(self, payload: Mapping[str, object]) -> None:
        delta = _mapping(payload.get("delta"))
        text = _text(delta.get("text"))
        if text is not None:
            self.texts.append(text)
        piece = _text(_mapping(delta.get("toolUse")).get("input"))
        call = self.open_calls.get(payload.get("contentBlockIndex"))
        if piece is not None and call is not None:
            call.parts.append(piece)

    def _close(self, index: object) -> None:
        call = self.open_calls.pop(index, None)
        if call is not None:
            self.tool_calls.append(ToolCall(call.name, call.tool_use_id, "".join(call.parts)))

    def transcript(self) -> Transcript:
        # A stream that ended inside a tool call still shows that call.
        for index in list(self.open_calls):
            self._close(index)
        return Transcript(
            reply="".join(self.texts),
            tool_calls=tuple(self.tool_calls),
            hook_decisions=tuple(self.hook_decisions),
            stop_reasons=tuple(self.stop_reasons),
            errors=tuple(self.errors),
        )


def read_stream(events: Iterable[object]) -> Transcript:
    """Return the transcript of `events`, the items of the stream of InvokeHarness.

    Never raises on the shape of an event: what is not a known event is left out.
    """
    collector = _Collector()
    for event in events:
        for key, payload in _mapping(event).items():
            collector.add(key, _mapping(payload))
    return collector.transcript()


def format_transcript(transcript: Transcript) -> str:
    """Return the transcript as lines of text: reply, tool calls, hooks, stops and errors."""
    lines = ["reply:", transcript.reply or "(none)", "", "tool calls:"]
    lines += [f"  {call.name} {call.input or '{}'}" for call in transcript.tool_calls] or [
        "  (none)"
    ]
    lines += ["", "hook decisions:"]
    lines += [
        f"  {hook.event} {hook.name}: {hook.decision or 'no decision'}"
        + (f" ({hook.reason})" if hook.reason else "")
        for hook in transcript.hook_decisions
    ] or ["  (none)"]
    lines += ["", "stop reasons: " + (", ".join(transcript.stop_reasons) or "(none)")]
    lines += [f"error: {error}" for error in transcript.errors]
    return "\n".join(lines)


def _hook_decision(payload: Mapping[str, object]) -> HookDecision:
    return HookDecision(
        name=_text(payload.get("name")) or "unknown",
        event=_text(payload.get("type")) or "unknown",
        decision=_text(payload.get("decision")),
        reason=_text(payload.get("reason")),
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None
