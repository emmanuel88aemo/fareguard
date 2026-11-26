import pytest

from fareguard.tool_names import normalise_tool_name

TOOLS = ("read_ledger", "list_pending", "request_approval", "launch_job")


@pytest.mark.parametrize("tool", TOOLS)
def test_exact_gateway_name_is_reduced_to_the_tool(tool: str) -> None:
    assert normalise_tool_name(f"fareguard___{tool}") == tool


@pytest.mark.parametrize("tool", TOOLS)
def test_tool_name_without_a_prefix_does_not_select_the_tool(tool: str) -> None:
    assert normalise_tool_name(tool) == f"unprefixed:{tool}"


@pytest.mark.parametrize(
    "name",
    [
        "other___read_ledger",
        "evil___launch_job",
        "fareguard-tools___launch_job",
        "Fareguard___launch_job",
        "a___fareguard___launch_job",
        "fareguard___a___launch_job",
        "fareguard___fareguard___launch_job",
        "fareguard____launch_job",
        "fareguard__launch_job",
        " fareguard___launch_job",
        "fareguard___launch_job\n",
        "fareguard___delete_ledger",
        "fareguard___",
        "unprefixed:launch_job",
        "shell",
        "___",
        "",
    ],
)
def test_any_other_name_is_left_unchanged(name: str) -> None:
    assert normalise_tool_name(name) == name
