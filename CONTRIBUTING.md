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
- The scope is lower case: `gate`, `tools`, `infra`, `stress`, `docs`.
- A breaking change adds `!` before the colon.

Use the body to explain why, not what. When a commit fixes a rule that failed under
testing, name the stress case in the body (for example `Stress case: A5`).

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
- IAM policies name exact actions and resources. A wildcard needs a comment that justifies it.
- `terraform fmt` and `terraform validate` must pass.

## Deployment

Deployment runs from GitHub Actions, never from a laptop:

- The workflow authenticates to AWS with GitHub OIDC and a short-lived role. No long-lived
  access keys are stored as secrets.
- `terraform plan` runs on every pull request that touches `infra/`.
- `terraform apply` runs only from `main`, through a protected environment that requires
  manual approval.

The deployment workflow is added together with the first Terraform code.

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
