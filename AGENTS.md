# Instructions for AI coding assistants

Read `CONTRIBUTING.md` first; every rule there applies to you. In addition:

- Do one task per branch and per pull request. Do not touch files outside its scope.
- Say which commit of `main` you read before you start.
- Never commit directly to `main` and never merge your own pull request.
- Never deploy, apply Terraform or call AWS on your own. A person does that.
- Do not copy code from private repositories into this one. This repository is public.
- If a requirement is missing or two documents disagree, write that down and stop.
- Before you finish, run `ruff check . && ruff format --check . && mypy && pytest` and
  report the result, including failures.
