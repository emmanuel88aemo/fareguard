import json
from collections.abc import Mapping

import pytest
from botocore.exceptions import ClientError

import invoke_harness as ih

# A made-up value with the shape of a real ARN; the account is twelve zeros.
HARNESS_ARN = "arn:aws:bedrock-agentcore:us-east-1:000000000000:harness/fareguard_dev-abcdefghij"
SESSION_ID = "session-0123456789012345678901234567890"


class FakeRuntimeClient:
    def __init__(self, events: list[object], error: Exception | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.regions: list[str] = []
        self._events = events
        self._error = error

    def invoke_harness(self, **kwargs: object) -> Mapping[str, object]:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return {"stream": self._events}

    def make(self, region: str) -> "FakeRuntimeClient":
        self.regions.append(region)
        return self


def _text(text: str) -> object:
    return {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": text}}}


def test_a_generated_session_id_has_the_required_length() -> None:
    session_id = ih.new_session_id()

    assert 33 <= len(session_id) <= 100
    assert ih.SESSION_ID.fullmatch(session_id)
    assert session_id != ih.new_session_id()


def test_the_request_overrides_nothing_of_the_harness() -> None:
    assert ih.build_request(HARNESS_ARN, SESSION_ID, "hello") == {
        "harnessArn": HARNESS_ARN,
        "runtimeSessionId": SESSION_ID,
        "messages": [{"role": "user", "content": [{"text": "hello"}]}],
    }


def test_the_reply_is_printed_and_the_message_is_sent_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeRuntimeClient(
        [_text("Two discs queued."), {"messageStop": {"stopReason": "end_turn"}}]
    )

    code = ih.main(
        ["--harness-arn", HARNESS_ARN, "--session-id", SESSION_ID, "What is queued?"],
        make_client=client.make,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert client.regions == ["us-east-1"]
    assert client.calls == [ih.build_request(HARNESS_ARN, SESSION_ID, "What is queued?")]
    assert f"runtime session id: {SESSION_ID}" in out
    assert "Two discs queued." in out
    assert "stop reasons: end_turn" in out


def test_dry_run_prints_the_request_and_builds_no_client(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeRuntimeClient([])

    code = ih.main(["--harness-arn", HARNESS_ARN, "--dry-run", "hello"], make_client=client.make)

    out = capsys.readouterr().out
    request = json.loads(out[out.index("{") :])
    assert code == 0
    assert client.regions == []
    assert request["harnessArn"] == HARNESS_ARN
    assert ih.SESSION_ID.fullmatch(request["runtimeSessionId"])


def test_a_model_the_stream_rejects_is_printed_word_for_word(
    capsys: pytest.CaptureFixture[str],
) -> None:
    message = "The model us.amazon.nova-2-lite-v1:0 is not supported by this harness."
    client = FakeRuntimeClient([{"runtimeClientError": {"message": message}}])

    code = ih.main(["--harness-arn", HARNESS_ARN, "hello"], make_client=client.make)

    assert code == 1
    assert message in capsys.readouterr().out


def test_an_error_of_the_api_is_printed_word_for_word(capsys: pytest.CaptureFixture[str]) -> None:
    message = "Invocation of model ID us.amazon.nova-2-lite-v1:0 is not supported."
    error = ClientError(
        {"Error": {"Code": "ValidationException", "Message": message}}, "InvokeHarness"
    )
    client = FakeRuntimeClient([], error)

    code = ih.main(["--harness-arn", HARNESS_ARN, "hello"], make_client=client.make)

    err = capsys.readouterr().err
    assert code == 1
    assert message in err
    assert '"Code": "ValidationException"' in err


@pytest.mark.parametrize(
    ("argv", "fragment"),
    [
        (["hello"], "FAREGUARD_HARNESS_ARN"),
        (["--harness-arn", "not-an-arn", "hello"], "FAREGUARD_HARNESS_ARN"),
        (["--harness-arn", HARNESS_ARN, "  "], "message"),
        (["--harness-arn", HARNESS_ARN, "--session-id", "short", "hello"], "33 to 100"),
        (["--harness-arn", HARNESS_ARN, "--session-id", "x" * 101, "hello"], "33 to 100"),
    ],
)
def test_bad_arguments_stop_before_any_client_is_built(
    argv: list[str],
    fragment: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ih.HARNESS_ARN_VARIABLE, raising=False)
    client = FakeRuntimeClient([])

    code = ih.main(argv, make_client=client.make)

    assert code == 1
    assert client.regions == []
    assert fragment in capsys.readouterr().err


def test_the_harness_arn_is_read_from_the_environment(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ih.HARNESS_ARN_VARIABLE, HARNESS_ARN)
    client = FakeRuntimeClient([])

    code = ih.main(["hello"], make_client=client.make)

    assert code == 0
    assert client.calls[0]["harnessArn"] == HARNESS_ARN
    assert "reply:" in capsys.readouterr().out
