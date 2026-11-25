"""Build the configuration of the AgentCore harness: the arguments of CreateHarness.

Every setting that matters is stated, so that none is left to a managed
default of the service: the model, the tools the model is offered, the
memory, the hooks and the limits. The reasons are in
docs/decisions/0007-harness-with-a-pinned-model-and-no-built-in-tools.md.

The configuration is a default, not a boundary: a caller of InvokeHarness can
replace everything here except the hooks. The rules hold through the hooks
and through IAM.
"""

from dataclasses import dataclass
from typing import Literal, TypedDict

from fareguard.gate.evaluate import LAUNCH_JOB, LIST_PENDING, READ_LEDGER, REQUEST_APPROVAL
from fareguard.hook.decide import TARGET_SEPARATOR

# The Amazon Nova 2 Lite inference profile of the US regions. The execution role in
# infra/main/iam_harness.tf may invoke this model and no other.
MODEL_ID = "us.amazon.nova-2-lite-v1:0"

# The name of the gateway tool entry, and the name of the gateway target that prefixes
# every tool name (infra/main/gateway.tf). Both happen to be the same word.
GATEWAY_TOOL_NAME = "fareguard"
GATEWAY_TARGET_NAME = "fareguard"

TOOL_NAMES: tuple[str, ...] = (READ_LEDGER, LIST_PENDING, REQUEST_APPROVAL, LAUNCH_JOB)

MAX_SELECTOR_LENGTH = 64
MAX_HOOK_TIMEOUT_SECONDS = 900


class HarnessConfigError(ValueError):
    """An input from which no harness configuration may be built."""


@dataclass(frozen=True)
class HarnessLimits:
    """The limits of one invocation, and how long the harness waits for the hook.

    `max_tokens` is the total of output tokens over all model calls of an invocation.
    """

    max_iterations: int
    max_tokens: int
    timeout_seconds: int
    hook_timeout_seconds: int


@dataclass(frozen=True)
class HarnessInputs:
    """What the configuration is built from. The ARNs come from `terraform output`."""

    harness_name: str
    model_id: str
    system_prompt: str
    gateway_arn: str
    hook_function_arn: str
    execution_role_arn: str
    tool_names: tuple[str, ...]
    limits: HarnessLimits


# The TypedDicts below spell their keys as the CreateHarness API does.
class BedrockModelConfig(TypedDict):
    """The Bedrock model the harness calls."""

    modelId: str


class ModelConfig(TypedDict):
    """The model provider; only Bedrock is used."""

    bedrockModelConfig: BedrockModelConfig


class TextBlock(TypedDict):
    """One block of the system prompt."""

    text: str


class GatewayOutboundAuth(TypedDict):
    """How the harness signs its calls to the gateway: with its execution role."""

    awsIam: dict[str, str]


class GatewayConfig(TypedDict):
    """The gateway and how to authenticate to it."""

    gatewayArn: str
    outboundAuth: GatewayOutboundAuth


class GatewayToolConfig(TypedDict):
    """The configuration of a tool entry of type agentcore_gateway."""

    agentCoreGateway: GatewayConfig


class GatewayTool(TypedDict):
    """A tool entry that offers every tool of one gateway."""

    type: Literal["agentcore_gateway"]
    name: str
    config: GatewayToolConfig


class DisabledMemory(TypedDict):
    """The explicit choice of no memory."""

    disabled: dict[str, str]


class LambdaTarget(TypedDict):
    """The function a hook invokes; a failure of the function denies."""

    arn: str
    timeoutSeconds: int
    failureMode: Literal["deny"]


# "lambda" is a keyword, so this one cannot be written as a class.
HookTarget = TypedDict("HookTarget", {"lambda": LambdaTarget})


class HookSpec(TypedDict):
    """One registered hook."""

    name: str
    target: HookTarget


class BeforeInvocationHook(TypedDict):
    """A hook on the event before_invocation."""

    beforeInvocation: HookSpec


class BeforeToolCallHook(TypedDict):
    """A hook on the event before_tool_call."""

    beforeToolCall: HookSpec


class AfterToolCallHook(TypedDict):
    """A hook on the event after_tool_call."""

    afterToolCall: HookSpec


type Hook = BeforeInvocationHook | BeforeToolCallHook | AfterToolCallHook


class HarnessConfig(TypedDict):
    """The keyword arguments of the CreateHarness operation."""

    harnessName: str
    executionRoleArn: str
    model: ModelConfig
    systemPrompt: list[TextBlock]
    tools: list[GatewayTool]
    allowedTools: list[str]
    memory: DisabledMemory
    hooks: list[Hook]
    maxIterations: int
    maxTokens: int
    timeoutSeconds: int


def build_harness_config(inputs: HarnessInputs) -> HarnessConfig:
    """Return the arguments of CreateHarness for `inputs`.

    Raises:
        HarnessConfigError: if the model is not the pinned one, the tools are not exactly
            the four of the agent, a text is empty or a limit is out of range.
    """
    _check_texts(inputs)
    _check_limits(inputs.limits)
    if inputs.model_id != MODEL_ID:
        message = f"the model id must be {MODEL_ID}"
        raise HarnessConfigError(message)
    return {
        "harnessName": inputs.harness_name,
        "executionRoleArn": inputs.execution_role_arn,
        "model": {"bedrockModelConfig": {"modelId": inputs.model_id}},
        "systemPrompt": [{"text": inputs.system_prompt}],
        "tools": [_gateway_tool(inputs.gateway_arn)],
        "allowedTools": allowed_tool_selectors(inputs.tool_names),
        "memory": {"disabled": {}},
        "hooks": _hooks(inputs.hook_function_arn, inputs.limits.hook_timeout_seconds),
        "maxIterations": inputs.limits.max_iterations,
        "maxTokens": inputs.limits.max_tokens,
        "timeoutSeconds": inputs.limits.timeout_seconds,
    }


def allowed_tool_selectors(tool_names: tuple[str, ...]) -> list[str]:
    """Return the allowedTools selectors of the four tools, in the order of `tool_names`.

    Raises:
        HarnessConfigError: if `tool_names` is not exactly the four tools of the agent,
            each once.
    """
    if len(tool_names) != len(TOOL_NAMES) or set(tool_names) != set(TOOL_NAMES):
        message = "the allowed tools must be exactly " + ", ".join(TOOL_NAMES) + ", each once"
        raise HarnessConfigError(message)
    # A plain name in allowedTools selects a built-in tool; "@<tool entry>/<tool>" selects
    # a configured one, and a gateway names its tools "<target>___<tool>". A list that
    # holds only these four selectors is therefore what keeps every built-in tool away
    # from the model: shell, read, write, edit, todo_write, retrieve_context, subagent
    # and web_fetch, and any built-in the service adds later. No "*", no "@builtin" and
    # no "@fareguard" (every tool of the gateway) may be added here.
    selectors = [
        f"@{GATEWAY_TOOL_NAME}/{GATEWAY_TARGET_NAME}{TARGET_SEPARATOR}{name}" for name in tool_names
    ]
    too_long = [selector for selector in selectors if len(selector) > MAX_SELECTOR_LENGTH]
    if too_long:
        message = f"an allowedTools selector is longer than {MAX_SELECTOR_LENGTH} characters"
        raise HarnessConfigError(message)
    return selectors


def _check_texts(inputs: HarnessInputs) -> None:
    texts = {
        "harness name": inputs.harness_name,
        "system prompt": inputs.system_prompt,
        "gateway ARN": inputs.gateway_arn,
        "hook function ARN": inputs.hook_function_arn,
        "execution role ARN": inputs.execution_role_arn,
    }
    for label, text in texts.items():
        if not text.strip():
            message = f"the {label} must not be empty"
            raise HarnessConfigError(message)


def _check_limits(limits: HarnessLimits) -> None:
    values = {
        "max_iterations": limits.max_iterations,
        "max_tokens": limits.max_tokens,
        "timeout_seconds": limits.timeout_seconds,
        "hook_timeout_seconds": limits.hook_timeout_seconds,
    }
    for label, value in values.items():
        if value < 1:
            message = f"{label} must be at least 1"
            raise HarnessConfigError(message)
    if limits.hook_timeout_seconds > MAX_HOOK_TIMEOUT_SECONDS:
        message = f"hook_timeout_seconds must be at most {MAX_HOOK_TIMEOUT_SECONDS}"
        raise HarnessConfigError(message)


def _gateway_tool(gateway_arn: str) -> GatewayTool:
    """Return the one tool entry: the gateway, called with the execution role's signature."""
    return {
        "type": "agentcore_gateway",
        "name": GATEWAY_TOOL_NAME,
        "config": {"agentCoreGateway": {"gatewayArn": gateway_arn, "outboundAuth": {"awsIam": {}}}},
    }


def _hooks(hook_function_arn: str, timeout_seconds: int) -> list[Hook]:
    """Return the hook function registered on the three events it answers."""

    def spec(name: str) -> HookSpec:
        # failureMode deny: a hook that fails, times out or answers badly denies.
        target: LambdaTarget = {
            "arn": hook_function_arn,
            "timeoutSeconds": timeout_seconds,
            "failureMode": "deny",
        }
        return {"name": name, "target": {"lambda": target}}

    return [
        {"beforeInvocation": spec("fareguard_before_invocation")},
        {"beforeToolCall": spec("fareguard_before_tool_call")},
        {"afterToolCall": spec("fareguard_after_tool_call")},
    ]
