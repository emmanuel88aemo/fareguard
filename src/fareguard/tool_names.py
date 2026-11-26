"""The names under which a call of one of the tools arrives.

The hook and the tools handler both receive a name that carries the gateway
target as a prefix, "<target>___<tool>". This module is the only place that
knows that format.
"""

from collections.abc import Mapping

from fareguard.gate.evaluate import LAUNCH_JOB, LIST_PENDING, READ_LEDGER, REQUEST_APPROVAL

# Must equal the name of the gateway target, `gateway_target_name` in infra/main/gateway.tf.
# If the two differ, every tool call is denied.
GATEWAY_TARGET_NAME = "fareguard"
TARGET_SEPARATOR = "___"
UNPREFIXED_MARK = "unprefixed:"

_TOOL_BY_GATEWAY_NAME: Mapping[str, str] = {
    f"{GATEWAY_TARGET_NAME}{TARGET_SEPARATOR}{tool}": tool
    for tool in (READ_LEDGER, LIST_PENDING, REQUEST_APPROVAL, LAUNCH_JOB)
}


def normalise_tool_name(name: str) -> str:
    """Return the tool that `name` selects, or a name that is none of the tools.

    Only exactly "fareguard___<tool>", for one of the four tools, is reduced to
    the tool. A tool name with no prefix is returned behind UNPREFIXED_MARK,
    because returned as it is it would select that tool. Every other name is
    returned unchanged. R1 therefore denies whatever did not arrive under the
    exact gateway name.
    """
    if name in _TOOL_BY_GATEWAY_NAME.values():
        return f"{UNPREFIXED_MARK}{name}"
    return _TOOL_BY_GATEWAY_NAME.get(name, name)
