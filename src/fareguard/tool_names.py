"""The names under which a call of one of the tools arrives.

The hook and the tools handler both receive a name that carries the gateway
target as a prefix, "<target>___<tool>". This module is the only place that
knows that format.
"""

# Must equal the name of the gateway target, `gateway_target_name` in infra/main/gateway.tf.
GATEWAY_TARGET_NAME = "fareguard"
TARGET_SEPARATOR = "___"


def normalise_tool_name(name: str) -> str:
    """Return the tool name without the gateway target: what follows the last "___"."""
    return name.rpartition(TARGET_SEPARATOR)[2]
