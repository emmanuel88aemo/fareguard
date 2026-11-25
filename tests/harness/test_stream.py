from fareguard.harness.stream import (
    HookDecision,
    ToolCall,
    Transcript,
    format_transcript,
    read_stream,
)


def _tool_use(index: int, name: str, tool_use_id: str, *pieces: str) -> list[object]:
    start = {"toolUse": {"name": name, "toolUseId": tool_use_id}}
    return [
        {"contentBlockStart": {"contentBlockIndex": index, "start": start}},
        *(
            {"contentBlockDelta": {"contentBlockIndex": index, "delta": {"toolUse": {"input": p}}}}
            for p in pieces
        ),
        {"contentBlockStop": {"contentBlockIndex": index}},
    ]


def _text(index: int, text: str) -> object:
    return {"contentBlockDelta": {"contentBlockIndex": index, "delta": {"text": text}}}


def test_text_deltas_are_joined_into_the_reply() -> None:
    events = [{"messageStart": {"role": "assistant"}}, _text(0, "Two discs "), _text(0, "queued.")]

    assert read_stream(events).reply == "Two discs queued."


def test_a_tool_call_is_read_with_its_input_joined() -> None:
    events = _tool_use(
        1, "fareguard___launch_job", "t1", '{"disc_id": "d1", ', '"approval_ref": "a1"}'
    )

    assert read_stream(events).tool_calls == (
        ToolCall("fareguard___launch_job", "t1", '{"disc_id": "d1", "approval_ref": "a1"}'),
    )


def test_tool_calls_of_several_messages_keep_their_order() -> None:
    events = [
        *_tool_use(0, "fareguard___read_ledger", "t1"),
        {"messageStop": {"stopReason": "tool_use"}},
        *_tool_use(0, "fareguard___list_pending", "t2"),
        {"messageStop": {"stopReason": "end_turn"}},
    ]

    transcript = read_stream(events)

    assert [call.name for call in transcript.tool_calls] == [
        "fareguard___read_ledger",
        "fareguard___list_pending",
    ]
    assert transcript.stop_reasons == ("tool_use", "end_turn")


def test_a_tool_call_the_stream_never_closed_is_still_shown() -> None:
    events = _tool_use(0, "fareguard___read_ledger", "t1", "{}")[:-1]

    assert read_stream(events).tool_calls == (ToolCall("fareguard___read_ledger", "t1", "{}"),)


def test_a_block_that_starts_on_an_open_index_closes_the_earlier_call() -> None:
    events = [
        *_tool_use(0, "fareguard___read_ledger", "t1")[:-1],
        *_tool_use(0, "fareguard___list_pending", "t2"),
    ]

    assert [call.tool_use_id for call in read_stream(events).tool_calls] == ["t1", "t2"]


def test_a_tool_result_block_is_not_a_tool_call() -> None:
    events = [
        {
            "contentBlockStart": {
                "contentBlockIndex": 0,
                "start": {"toolResult": {"toolUseId": "t1"}},
            }
        },
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolResult": [{"text": "x"}]}}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
    ]

    transcript = read_stream(events)

    assert transcript.tool_calls == ()
    assert transcript.reply == ""


def test_a_hook_decision_is_read_with_its_reason() -> None:
    event = {
        "hookEvent": {
            "hookEventId": "1234abcd-12ab-34cd-56ef-1234567890ab",
            "name": "fareguard_before_tool_call",
            "type": "before_tool_call",
            "decision": "deny",
            "reason": "R1: the requested tool does not exist",
        }
    }

    assert read_stream([event]).hook_decisions == (
        HookDecision(
            "fareguard_before_tool_call",
            "before_tool_call",
            "deny",
            "R1: the requested tool does not exist",
        ),
    )


def test_each_error_event_is_kept_word_for_word() -> None:
    events = [
        {
            "runtimeClientError": {
                "message": "The model us.amazon.nova-2-lite-v1:0 is not supported."
            }
        },
        {"validationException": {"message": "bad", "reason": "FieldValidationFailed"}},
        {"internalServerException": {"message": "oops"}},
    ]

    assert read_stream(events).errors == (
        'runtimeClientError: {"message": "The model us.amazon.nova-2-lite-v1:0 is not supported."}',
        'validationException: {"message": "bad", "reason": "FieldValidationFailed"}',
        'internalServerException: {"message": "oops"}',
    )


def test_events_of_an_unexpected_shape_are_left_out() -> None:
    events: list[object] = [
        None,
        "text",
        {"metadata": {"usage": {}}},
        {"contentBlockStart": "not a mapping"},
        {"contentBlockStart": {"contentBlockIndex": 0, "start": {"toolUse": {}}}},
        {"contentBlockDelta": {"contentBlockIndex": 5, "delta": {"toolUse": {"input": "{}"}}}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": 3}}},
        {"messageStop": {}},
        {"hookEvent": {}},
    ]

    assert read_stream(events) == Transcript(
        reply="",
        tool_calls=(),
        hook_decisions=(HookDecision("unknown", "unknown", None, None),),
        stop_reasons=("unknown",),
        errors=(),
    )


def test_a_tool_call_without_a_name_is_shown_as_unknown() -> None:
    events = [{"contentBlockStart": {"contentBlockIndex": 0, "start": {"toolUse": {"x": 1}}}}]

    assert read_stream(events).tool_calls == (ToolCall("unknown", "unknown", ""),)


def test_an_empty_transcript_says_so() -> None:
    assert format_transcript(read_stream([])) == "\n".join(
        [
            "reply:",
            "(none)",
            "",
            "tool calls:",
            "  (none)",
            "",
            "hook decisions:",
            "  (none)",
            "",
            "stop reasons: (none)",
        ]
    )


def test_a_transcript_is_formatted_in_full() -> None:
    transcript = Transcript(
        reply="Denied.",
        tool_calls=(
            ToolCall("fareguard___read_ledger", "t1", ""),
            ToolCall("fareguard___launch_job", "t2", '{"disc_id": "d1"}'),
        ),
        hook_decisions=(
            HookDecision("fareguard_before_invocation", "before_invocation", "allow", "allowed"),
            HookDecision("fareguard_before_tool_call", "before_tool_call", "deny", None),
            HookDecision("notify", "after_invocation", None, None),
        ),
        stop_reasons=("tool_use", "end_turn"),
        errors=('runtimeClientError: {"message": "x"}',),
    )

    assert format_transcript(transcript) == "\n".join(
        [
            "reply:",
            "Denied.",
            "",
            "tool calls:",
            "  fareguard___read_ledger {}",
            '  fareguard___launch_job {"disc_id": "d1"}',
            "",
            "hook decisions:",
            "  before_invocation fareguard_before_invocation: allow (allowed)",
            "  before_tool_call fareguard_before_tool_call: deny",
            "  after_invocation notify: no decision",
            "",
            "stop reasons: tool_use, end_turn",
            'error: runtimeClientError: {"message": "x"}',
        ]
    )
