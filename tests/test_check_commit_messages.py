from pathlib import Path

import pytest

import check_commit_messages as ccm


@pytest.mark.parametrize(
    "subject",
    [
        "feat: add spend gate hook",
        "fix(gate): reject reused approval references",
        "ci: run terraform validate on pull requests",
        "feat(api)!: rename launch tool",
        "Merge pull request #3 from emmanuel88aemo/feat/gate",
        'Revert "feat: add spend gate hook"',
    ],
)
def test_valid_subjects_have_no_errors(subject: str) -> None:
    assert ccm.subject_errors(subject) == []


@pytest.mark.parametrize(
    ("subject", "fragment"),
    [
        ("added the gate", "must look like"),
        ("feature: add gate", "must look like"),
        ("feat:add gate", "must look like"),
        ("feat(Gate): add gate", "must look like"),
        ("feat: Add gate", "lower case"),
        ("feat: add gate.", "period"),
        ("feat: " + "x" * 80, "limit"),
    ],
)
def test_invalid_subjects_explain_the_rule(subject: str, fragment: str) -> None:
    errors = ccm.subject_errors(subject)
    assert any(fragment in error for error in errors)


def test_one_subject_can_break_several_rules() -> None:
    errors = ccm.subject_errors("feat: Add " + "x" * 80 + ".")
    assert len(errors) == 3


def test_subject_in_file_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("# comment\n\nfix: close the loophole\n\nbody\n", encoding="utf-8")
    assert ccm.subject_in_file(message) == "fix: close the loophole"


def test_subject_in_empty_file_is_empty(tmp_path: Path) -> None:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("# only a comment\n", encoding="utf-8")
    assert ccm.subject_in_file(message) == ""


def test_main_accepts_a_valid_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("docs: describe the rule set\n", encoding="utf-8")
    assert ccm.main(["--file", str(message)]) == 0
    assert "follow the convention" in capsys.readouterr().out


def test_main_rejects_an_invalid_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("wip\n", encoding="utf-8")
    assert ccm.main(["--file", str(message)]) == 1
    assert "must look like" in capsys.readouterr().err
