"""Validate commit subjects against the Conventional Commits rules of this repository.

Usage:
    python scripts/check_commit_messages.py --range origin/main..HEAD
    python scripts/check_commit_messages.py --file .git/COMMIT_EDITMSG
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ALLOWED_TYPES: tuple[str, ...] = (
    "feat",
    "fix",
    "docs",
    "test",
    "refactor",
    "perf",
    "build",
    "ci",
    "chore",
    "revert",
)
MAX_SUBJECT_LENGTH = 72

_SUBJECT = re.compile(
    rf"^(?P<type>{'|'.join(ALLOWED_TYPES)})"
    r"(\((?P<scope>[a-z0-9][a-z0-9-]*)\))?"
    r"(?P<breaking>!)?: "
    r"(?P<summary>\S.*)$"
)
_GENERATED_PREFIXES: tuple[str, ...] = ("Merge ", "Revert ")


def subject_errors(subject: str) -> list[str]:
    """Return every rule the subject line breaks; an empty list means it is valid."""
    if subject.startswith(_GENERATED_PREFIXES):
        return []

    match = _SUBJECT.match(subject)
    if match is None:
        return [
            "must look like '<type>(<scope>): <summary>' with type in " + ", ".join(ALLOWED_TYPES)
        ]

    errors: list[str] = []
    summary = match.group("summary")
    if len(subject) > MAX_SUBJECT_LENGTH:
        errors.append(f"is {len(subject)} characters long; the limit is {MAX_SUBJECT_LENGTH}")
    if summary[0].isupper():
        errors.append("summary must start in lower case")
    if summary.endswith("."):
        errors.append("summary must not end with a period")
    return errors


def subjects_in_range(revision_range: str) -> list[str]:
    """Return the subject line of every commit in a git revision range."""
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "log", "--format=%s", revision_range],  # noqa: S607 - git from PATH is intended
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def subject_in_file(path: Path) -> str:
    """Return the first non-comment line of a commit message file."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            return line
    return ""


def main(argv: Sequence[str] | None = None) -> int:
    """Check the requested commits and return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--range", dest="revision_range", help="git revision range to check")
    source.add_argument("--file", type=Path, help="commit message file to check")
    args = parser.parse_args(argv)

    subjects = (
        subjects_in_range(args.revision_range)
        if args.revision_range is not None
        else [subject_in_file(args.file)]
    )

    failed = False
    for subject in subjects:
        for error in subject_errors(subject):
            failed = True
            print(f"✗ {subject!r}: {error}", file=sys.stderr)
    if not failed:
        print(f"✓ {len(subjects)} commit subject(s) follow the convention")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
