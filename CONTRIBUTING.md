# Contributing to Fareguard

These rules apply to every change, whether a person or an AI assistant writes it.
`main` is the only source of truth: if it is not merged there, it does not exist.

## Workflow

1. Branch from `main`. Name the branch `<type>/<short-description>`, for example `feat/spend-gate`.
2. Make small, atomic commits (see below).
3. Open a pull request. CI must be green before merging.
4. Merge with a merge commit so the atomic history is preserved. Do not push to `main` directly.

## Commits

One commit does one thing. If the summary needs the word "and", split the commit.
A commit must leave the repository working: lint, types and tests pass at every commit.

Subjects follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional-scope>): <summary>
```

| Type | Use it for |
|---|---|
| `feat` | A new capability of the agent or its tooling |
| `fix` | A bug fix, including a rule that failed a stress test |
| `docs` | Documentation only |
| `test` | Adding or correcting tests only |
| `refactor` | A change that neither fixes a bug nor adds a capability |
| `perf` | A performance or cost improvement |
| `build` | Packaging and dependencies |
| `ci` | Workflows and automation |
| `chore` | Repository upkeep |
| `revert` | Reverting an earlier commit |

Rules checked by CI and by the `commit-msg` hook:

- The summary starts in lower case, has no final period and uses the imperative ("add", not "added").
- The whole subject is at most 72 characters.
- The scope is lower case: `gate`, `ledger`, `hook`, `handlers`, `tools`, `infra`, `stress`,
  `docs`.
- A breaking change adds `!` before the colon.

Use the body to explain why, not what. When a commit fixes a rule that failed under
testing, name the stress case in the body (for example `Stress case: A5`).

## Pull requests

- **One concern per pull request.** A reviewer should be able to hold the whole change in mind.
  Aim for under 400 changed lines; split larger work into a sequence of pull requests.
- **The title follows the commit convention** (`feat(gate): deny reused approvals`). CI checks it.
- **The description fills in the template:** what changes, why, and how it was verified with the
  actual commands and results. "Tested" without evidence is not verification.
- **State what is not included** when a reader might expect it.
- **Refactors and behaviour changes go in separate pull requests.**
- **Draft pull requests** are for early feedback. Mark ready only when CI is green.
- **Review:** the owner reviews every pull request. The author answers each comment with a
  change or a reason. Nobody merges their own unreviewed work into `main`.
- **Never force-push a branch after review has started,** except to fix a commit message
  that CI rejected. Add commits instead, so the reviewer can see what changed.

## Naming

| Thing | Convention | Example |
|---|---|---|
| Branch | `<type>/<short-description>`, kebab-case | `feat/spend-gate` |
| Python module, function, variable | `snake_case` | `monthly_spend` |
| Python class | `PascalCase` | `ApprovalRecord` |
| Python constant | `UPPER_SNAKE_CASE` | `MAX_USD_PER_JOB` |
| Test | `test_<behaviour>` describing the outcome | `test_reused_approval_is_denied` |
| Agent tool | `snake_case` verb phrase | `request_approval` |
| Rule | `R<n>`, stable once published | `R4` |
| Stress case | `A<n>`, stable once published | `A5` |
| Terraform resource label | `snake_case` | `aws_lambda_function.spend_gate` |
| AWS resource name | `fareguard-<env>-<component>`, kebab-case | `fareguard-dev-spend-gate` |
| Environment variable | `FAREGUARD_<NAME>` | `FAREGUARD_MONTHLY_CAP_USD` |
| Decision record | `docs/decisions/NNNN-<title>.md` | `0001-enforce-rules-outside-the-model.md` |

Every AWS resource carries the tags `Project = fareguard`, `Environment` and `ManagedBy = terraform`.
Rule and stress-case identifiers are never renumbered: the write-up, the tests and the code refer to them.

## How work is organised

- **One issue per task.** An issue states the goal, the scope and how it will be verified.
  Its pull request closes it with `Closes #<n>`.
- **Decisions are written down.** A choice that is hard to reverse, or that someone will
  later ask "why?" about, gets a short record in `docs/decisions/` before the code changes.
- **Failures are kept.** When a rule fails a stress test, record the failing case in
  `docs/stress/` before fixing it. The fix commit references the case.
- **Versions** follow [Semantic Versioning](https://semver.org/). `CHANGELOG.md` is updated in
  the pull request that makes the change.

### Definition of done

A task is done when all of these are true:

1. CI is green and the pull request is merged into `main`.
2. New enforcement logic has a test that fails without it.
3. Documentation that describes the changed behaviour is updated in the same pull request.
4. For deployed changes: the change was verified in AWS and the evidence is in the pull request.

"Merged" and "works in AWS" are different states. Say which one you mean.

## Functions and modules

- **A function does one thing** and its name says what. If you need "and" to describe it, split it.
- **Small by default:** at most 5 parameters, 30 statements and a complexity of 8. Ruff enforces
  these limits; raising one needs a comment that explains why.
- **Decision logic is pure.** Functions that decide allow or deny take plain data and return a
  result. They do not call AWS, read the clock or read the environment. Handlers at the edge
  gather the inputs and call them. This is what makes the rules testable.
- **Explicit inputs and outputs.** No hidden global state; pass dependencies in.
- **Typed data, not loose dictionaries.** Use `dataclass(frozen=True)` or `TypedDict` for
  structured values that cross a function boundary.
- **Errors are specific.** Raise a named exception with a message that says what was expected.
  Never use a bare `except` or swallow an error silently; catching `Exception` is allowed only
  at a handler boundary that then denies.
- **Docstrings** describe the contract in one line, plus arguments and failure cases when they
  are not obvious. Comments explain why, never what.
- **No dead code:** no commented-out blocks, no unused parameters, no `print` in library code.
- **One concept per module.** A module that grows past about 300 lines is doing too much.

## Repository layout

```
src/fareguard/        Library code: pure decision logic and typed models
  gate/               Rule evaluation used by the hook
  ledger/             Storage behind the gate: the store contract and its implementations
  tools/              Implementations of the agent's tools
  handlers/           Thin AWS Lambda entry points; no business logic
infra/                Terraform: everything that exists in AWS
harness/              Harness configuration and the script that creates it
stress/               Adversarial cases and the runner that scores them
scripts/              Developer and CI utilities
tests/                Mirrors src/: tests/gate/test_caps.py tests src/fareguard/gate/caps.py
docs/
  decisions/          Decision records
  stress/             Recorded results, including failures
  architecture.md     How each rule is enforced
```

Rules for files:

- **A file lives where its kind lives.** Do not add top-level directories without a decision record.
- **Tests mirror the source tree,** one test module per source module.
- **File names** are `snake_case` for Python and Terraform, `kebab-case` for Markdown and YAML.
- **Generated and local files are never committed:** virtual environments, caches, Terraform
  state, plans, build output and `.env` files. If Git shows one, fix `.gitignore`.
- **Binary files** (screenshots, diagrams) go in `docs/assets/`, are kept small and are
  referenced from a document. No orphan files.
- **Delete, do not disable.** Remove files that are no longer used; Git keeps the history.
- **Configuration has one home.** Tool settings live in `pyproject.toml`, not in scattered files.

## Code standards

- **Python 3.12.** Every function, method and module-level constant is type annotated.
  `mypy --strict` must pass; `# type: ignore` needs a specific error code and a reason.
- **Ruff** formats and lints the code. Do not disable a rule without a comment that explains why.
- **Tests** live in `tests/` and run with `pytest`. Coverage of `src/fareguard` stays at or above 90 %.
  Any change to enforcement logic comes with a test that fails without it.
- **Fail closed.** Code that decides whether an action is allowed denies when input is
  missing, truncated or unexpected. It never defaults to allow.
- **Money is `Decimal`,** never `float`.
- **No secrets in the repository:** no keys, tokens, account IDs or `.env` files. Configuration
  comes from environment variables or Terraform variables.

## Infrastructure

- Everything in AWS is declared in `infra/` with Terraform. Nothing is created by hand in the console.
- **One exception:** the opt-in AWS tests (see [Tests against real DynamoDB](#tests-against-real-dynamodb))
  may create and delete one temporary table, tagged `Project = fareguard`, outside Terraform.
  It carries no `Environment` or `ManagedBy` tag because it belongs to no environment and
  Terraform does not manage it.
- IAM policies name exact actions and resources. A wildcard needs a comment that justifies it.
- `terraform fmt` and `terraform validate` must pass.

## Deployment

For now the owner deploys by hand, from a laptop:

- The owner runs `terraform plan` and `terraform apply`, following `infra/README.md`. Nobody
  else deploys, and no workflow does.
- The identity used is dedicated to this project and limited to it. It is not a personal
  administrator identity.
- CI formats and validates Terraform on every pull request. It holds no AWS credentials, so
  it cannot plan or apply.

**Planned, not built yet:** deployment from GitHub Actions, authenticated with GitHub OIDC and
a short-lived role instead of stored access keys, with `terraform plan` on every pull request
that touches `infra/` and `terraform apply` only from `main`, through a protected environment
that requires manual approval. Until that workflow exists, the list above is how deployment
works.

## Local setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install --hook-type pre-commit --hook-type commit-msg
```

Run everything CI runs:

```bash
ruff check . && ruff format --check . && mypy && pytest
```

### Tests against real DynamoDB

The tests marked `aws` run the ledger store against real DynamoDB. They are skipped unless
`FAREGUARD_RUN_AWS_TESTS` is exactly `1`. CI never sets it, so a person runs them by hand:

```bash
FAREGUARD_RUN_AWS_TESTS=1 pytest -m aws --no-cov
```

- The run **creates a real table and deletes it afterwards**, in the account and region of your
  default boto3 credentials. It costs a few cents.
- The table is on-demand, named `fareguard-it-<random suffix>` and tagged `Project = fareguard`.
  It is deleted even when a test fails. If a run is killed before it can clean up, delete the
  tables whose names start with `fareguard-it-` yourself.
- The credentials need `dynamodb:CreateTable`, `DescribeTable`, `TagResource`, `DeleteTable`,
  `Scan`, `Query`, `GetItem`, `PutItem`, `UpdateItem` and `DeleteItem` on `table/fareguard-it-*`.
- `--no-cov` is needed because the marker selects only part of the suite, which alone does not
  reach the coverage threshold.
