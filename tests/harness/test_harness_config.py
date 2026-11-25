import dataclasses

import botocore.session
import pytest
from botocore.exceptions import ParamValidationError
from botocore.model import Shape
from botocore.validate import validate_parameters

from fareguard.harness.config import (
    MODEL_ID,
    TOOL_NAMES,
    HarnessConfigError,
    HarnessInputs,
    HarnessLimits,
    allowed_tool_selectors,
    build_harness_config,
)

# Made-up values with the shape of real ARNs; the account is twelve zeros.
ROLE_ARN = "arn:aws:iam::000000000000:role/fareguard-dev-harness"
GATEWAY_ARN = (
    "arn:aws:bedrock-agentcore:us-east-1:000000000000:gateway/fareguard-dev-gateway-abcdefghij"
)
HOOK_ARN = "arn:aws:lambda:us-east-1:000000000000:function:fareguard-dev-hook"

LIMITS = HarnessLimits(
    max_iterations=12, max_tokens=4096, timeout_seconds=300, hook_timeout_seconds=15
)
INPUTS = HarnessInputs(
    harness_name="fareguard_dev",
    model_id=MODEL_ID,
    system_prompt="You are a dispatcher.",
    gateway_arn=GATEWAY_ARN,
    hook_function_arn=HOOK_ARN,
    execution_role_arn=ROLE_ARN,
    tool_names=TOOL_NAMES,
    limits=LIMITS,
)


def test_the_model_is_stated_and_is_the_nova_2_lite_inference_profile() -> None:
    config = build_harness_config(INPUTS)

    assert config["model"] == {"bedrockModelConfig": {"modelId": "us.amazon.nova-2-lite-v1:0"}}


@pytest.mark.parametrize(
    "model_id", ["", "global.anthropic.claude-opus-5", "amazon.nova-2-lite-v1:0"]
)
def test_another_model_is_refused(model_id: str) -> None:
    inputs = dataclasses.replace(INPUTS, model_id=model_id)

    with pytest.raises(HarnessConfigError, match="model id"):
        build_harness_config(inputs)


def test_the_gateway_is_the_only_tool_source() -> None:
    config = build_harness_config(INPUTS)

    assert config["tools"] == [
        {
            "type": "agentcore_gateway",
            "name": "fareguard",
            "config": {
                "agentCoreGateway": {"gatewayArn": GATEWAY_ARN, "outboundAuth": {"awsIam": {}}}
            },
        }
    ]


def test_exactly_the_four_tools_are_allowed() -> None:
    config = build_harness_config(INPUTS)

    assert config["allowedTools"] == [
        "@fareguard/fareguard___read_ledger",
        "@fareguard/fareguard___list_pending",
        "@fareguard/fareguard___request_approval",
        "@fareguard/fareguard___launch_job",
    ]


def test_no_selector_can_match_a_built_in_tool() -> None:
    config = build_harness_config(INPUTS)

    # A built-in tool is selected by a plain name, by "*" or by "@builtin".
    assert all(
        selector.startswith("@fareguard/fareguard___") for selector in config["allowedTools"]
    )
    assert all("*" not in selector for selector in config["allowedTools"])


@pytest.mark.parametrize(
    "tool_names",
    [
        (),
        TOOL_NAMES[:3],
        (*TOOL_NAMES, "shell"),
        (*TOOL_NAMES[:3], "shell"),
        (*TOOL_NAMES[:3], TOOL_NAMES[0]),
        (*TOOL_NAMES, TOOL_NAMES[0]),
        ("*",),
    ],
)
def test_any_other_list_of_tools_is_refused(tool_names: tuple[str, ...]) -> None:
    with pytest.raises(HarnessConfigError, match="exactly"):
        allowed_tool_selectors(tool_names)

    with pytest.raises(HarnessConfigError, match="exactly"):
        build_harness_config(dataclasses.replace(INPUTS, tool_names=tool_names))


def test_a_selector_that_is_too_long_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fareguard.harness.config.GATEWAY_TOOL_NAME", "g" * 40)

    with pytest.raises(HarnessConfigError, match="longer than 64"):
        allowed_tool_selectors(TOOL_NAMES)


def test_the_hook_answers_three_events_and_a_failure_denies() -> None:
    config = build_harness_config(INPUTS)

    target = {"lambda": {"arn": HOOK_ARN, "timeoutSeconds": 15, "failureMode": "deny"}}
    assert config["hooks"] == [
        {"beforeInvocation": {"name": "fareguard_before_invocation", "target": target}},
        {"beforeToolCall": {"name": "fareguard_before_tool_call", "target": target}},
        {"afterToolCall": {"name": "fareguard_after_tool_call", "target": target}},
    ]


def test_memory_is_disabled_explicitly() -> None:
    assert build_harness_config(INPUTS)["memory"] == {"disabled": {}}


def test_the_name_the_role_the_prompt_and_the_limits_are_passed_on() -> None:
    config = build_harness_config(INPUTS)

    assert config["harnessName"] == "fareguard_dev"
    assert config["executionRoleArn"] == ROLE_ARN
    assert config["systemPrompt"] == [{"text": "You are a dispatcher."}]
    assert config["maxIterations"] == 12
    assert config["maxTokens"] == 4096
    assert config["timeoutSeconds"] == 300


def test_nothing_is_set_beyond_the_expected_keys() -> None:
    assert set(build_harness_config(INPUTS)) == {
        "harnessName",
        "executionRoleArn",
        "model",
        "systemPrompt",
        "tools",
        "allowedTools",
        "memory",
        "hooks",
        "maxIterations",
        "maxTokens",
        "timeoutSeconds",
    }


@pytest.mark.parametrize(
    "field",
    ["harness_name", "system_prompt", "gateway_arn", "hook_function_arn", "execution_role_arn"],
)
@pytest.mark.parametrize("text", ["", "   "])
def test_an_empty_text_is_refused(field: str, text: str) -> None:
    texts = {
        "harness_name": INPUTS.harness_name,
        "system_prompt": INPUTS.system_prompt,
        "gateway_arn": INPUTS.gateway_arn,
        "hook_function_arn": INPUTS.hook_function_arn,
        "execution_role_arn": INPUTS.execution_role_arn,
    }
    texts[field] = text
    inputs = HarnessInputs(model_id=MODEL_ID, tool_names=TOOL_NAMES, limits=LIMITS, **texts)

    with pytest.raises(HarnessConfigError, match="must not be empty"):
        build_harness_config(inputs)


@pytest.mark.parametrize(
    "field", ["max_iterations", "max_tokens", "timeout_seconds", "hook_timeout_seconds"]
)
@pytest.mark.parametrize("value", [0, -1])
def test_a_limit_below_one_is_refused(field: str, value: int) -> None:
    inputs = dataclasses.replace(INPUTS, limits=dataclasses.replace(LIMITS, **{field: value}))

    with pytest.raises(HarnessConfigError, match=f"{field} must be at least 1"):
        build_harness_config(inputs)


def test_a_hook_timeout_above_the_service_limit_is_refused() -> None:
    inputs = dataclasses.replace(
        INPUTS, limits=dataclasses.replace(LIMITS, hook_timeout_seconds=901)
    )

    with pytest.raises(HarnessConfigError, match="at most 900"):
        build_harness_config(inputs)


def _create_harness_shape() -> Shape:
    model = botocore.session.get_session().get_service_model("bedrock-agentcore-control")
    shape = model.operation_model("CreateHarness").input_shape
    assert shape is not None
    return shape


def test_the_configuration_is_accepted_by_the_create_harness_model_of_boto3() -> None:
    # Builds no client and makes no call: the arguments are checked against the
    # shape of CreateHarness in the service model that ships with botocore.
    shape = _create_harness_shape()

    validate_parameters(dict(build_harness_config(INPUTS)), shape)


def test_the_service_model_refuses_a_key_it_does_not_know() -> None:
    # Shows that the check above can fail.
    shape = _create_harness_shape()
    arguments = {**build_harness_config(INPUTS), "allowedTools": "shell"}

    with pytest.raises(ParamValidationError):
        validate_parameters(arguments, shape)
