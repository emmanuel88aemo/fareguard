from pathlib import Path

import pytest

CONFTEST = Path(__file__).with_name("conftest.py")
TESTS = """
import pytest

@pytest.fixture
def resource():
    raise AssertionError("the fixture of a skipped test must not be set up")

@pytest.mark.aws
def test_marked(resource):
    pass

def test_unmarked():
    pass
"""


@pytest.fixture
def project(pytester: pytest.Pytester) -> pytest.Pytester:
    """A throwaway project with this repository's conftest, one aws test and one plain test."""
    pytester.makeini("[pytest]\nmarkers = aws")
    pytester.makeconftest(CONFTEST.read_text())
    pytester.makepyfile(TESTS)
    return pytester


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes", " 1"])
def test_aws_tests_are_skipped_without_the_exact_opt_in(
    project: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    monkeypatch.delenv("FAREGUARD_RUN_AWS_TESTS", raising=False)
    if value is not None:
        monkeypatch.setenv("FAREGUARD_RUN_AWS_TESTS", value)

    project.runpytest().assert_outcomes(passed=1, skipped=1)


def test_aws_tests_run_when_opted_in(
    project: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAREGUARD_RUN_AWS_TESTS", "1")

    project.runpytest().assert_outcomes(passed=1, errors=1)
