import pytest

from fareguard.tool_names import normalise_tool_name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("launch_job", "launch_job"),
        ("target___launch_job", "launch_job"),
        ("a___b___read_ledger", "read_ledger"),
        ("target___", ""),
        ("___", ""),
        ("launch__job", "launch__job"),
        ("", ""),
    ],
)
def test_normalise_tool_name_keeps_what_follows_the_last_separator(
    name: str, expected: str
) -> None:
    assert normalise_tool_name(name) == expected
