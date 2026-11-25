import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

import create_harness as ch
from fareguard.harness.config import MODEL_ID

# Made-up values with the shape of real ARNs; the account is twelve zeros.
HARNESS_ARN = "arn:aws:bedrock-agentcore:us-east-1:000000000000:harness/fareguard_dev-abcdefghij"
OUTPUTS: Mapping[str, object] = {
    "harness_name": "fareguard_dev",
    "gateway_arn": "arn:aws:bedrock-agentcore:us-east-1:000000000000:gateway/fareguard-abcdefghij",
    "hook_function_arn": "arn:aws:lambda:us-east-1:000000000000:function:fareguard-dev-hook",
    "harness_execution_role_arn": "arn:aws:iam::000000000000:role/fareguard-dev-harness",
}


class FakeControlClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.regions: list[str] = []
        self._error = error

    def create_harness(self, **kwargs: object) -> Mapping[str, object]:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return {"harness": {"arn": HARNESS_ARN, "status": "CREATING"}}

    def make(self, region: str) -> "FakeControlClient":
        self.regions.append(region)
        return self


def _outputs(_directory: Path) -> Mapping[str, object]:
    return OUTPUTS


def test_dry_run_prints_the_configuration_and_builds_no_client(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeControlClient()

    code = ch.main(["--dry-run"], read_outputs=_outputs, make_client=client.make)

    config = json.loads(capsys.readouterr().out)
    assert code == 0
    assert client.regions == []
    assert client.calls == []
    assert config["harnessName"] == "fareguard_dev"
    assert config["model"] == {"bedrockModelConfig": {"modelId": MODEL_ID}}
    assert config["systemPrompt"][0]["text"] == ch.SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def test_the_harness_is_created_once_in_the_region_of_the_gateway(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeControlClient()

    code = ch.main([], read_outputs=_outputs, make_client=client.make)

    assert code == 0
    assert client.regions == ["us-east-1"]
    assert len(client.calls) == 1
    assert client.calls[0]["executionRoleArn"] == OUTPUTS["harness_execution_role_arn"]
    assert f"harness ARN: {HARNESS_ARN}" in capsys.readouterr().out


def test_an_error_of_the_api_is_printed_as_it_came(capsys: pytest.CaptureFixture[str]) -> None:
    error = ClientError(
        {"Error": {"Code": "ValidationException", "Message": "the model is not supported"}},
        "CreateHarness",
    )

    code = ch.main([], read_outputs=_outputs, make_client=FakeControlClient(error).make)

    assert code == 1
    assert "ValidationException" in capsys.readouterr().err


@pytest.mark.parametrize("missing", sorted(OUTPUTS))
def test_a_missing_output_stops_before_any_client_is_built(
    missing: str, capsys: pytest.CaptureFixture[str]
) -> None:
    client = FakeControlClient()
    outputs = {name: value for name, value in OUTPUTS.items() if name != missing}

    code = ch.main([], read_outputs=lambda _directory: outputs, make_client=client.make)

    assert code == 1
    assert client.regions == []
    assert missing in capsys.readouterr().err


def test_a_gateway_arn_without_a_region_is_refused() -> None:
    with pytest.raises(ch.OutputsError, match="region"):
        ch.region_of("not-an-arn")


def test_terraform_outputs_are_read_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    printed = json.dumps({"gateway_arn": {"value": "x", "type": "string"}, "odd": 1})

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        assert argv == ["terraform", "output", "-json"]
        return subprocess.CompletedProcess(argv, 0, stdout=printed, stderr="")

    monkeypatch.setattr(subprocess, "run", run)

    assert ch.read_terraform_outputs(Path()) == {"gateway_arn": "x"}


@pytest.mark.parametrize("printed", ["not json", "[]"])
def test_unreadable_terraform_outputs_are_an_error(
    printed: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, stdout=printed, stderr="")

    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(ch.OutputsError):
        ch.read_terraform_outputs(Path())
