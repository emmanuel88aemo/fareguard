# 0009. Seed and reset outside the store

- Status: Accepted
- Date: 2026-11-26

## Context

A stress round needs the ledger in a known state, and a clean table before the next round.
The store has no operation that adds a disc or deletes anything, on purpose: the object the
tools Lambda holds must not be able to do either (records 0002 and 0008).

## Decision

**`scripts/seed.py` writes the table directly, and only a person runs it.** It uses a
DynamoDB client of its own, with an admin profile, never a role of the agent.

- `seed` puts each fixture disc with the condition that it does not exist, then the planted
  event with a plain `PutItem`. A disc that exists stops the run: replacing it would erase
  its spend and its `pending_approval_ref`.
- `reset --yes` scans the table and deletes every item, events included.
- `show` only reads, through the store and `read_ledger`.

**The fixture is typed constants in `fareguard.ops.seed_data`,** with a test that ties the
durations to the caps. The store and its contract do not change.

## Alternatives considered

- **Add `add_disc` and `clear` to the store.** The tools Lambda would then hold an object
  that can delete the event log.
- **Destroy and recreate the table with Terraform.** Slower, and it changes infrastructure
  to change data.
- **Seed in one transaction.** Atomic, but the planted event would no longer arrive as an
  ordinary write, and a failed seed is repaired by `reset` anyway.

## Consequences

- The event log is append-only for the agent and for the store, not for whoever holds
  `dynamodb:Scan` and `DeleteItem` on the table. `reset` has no check of the environment:
  it deletes from whichever table `terraform output` names. Only `dev` exists today; a
  second environment needs a guard first.
- The durations are chosen against the default limits of `infra/main/variables.tf`. If the
  deployed limits change, the test of `seed_data` still passes and the fixture is wrong.
- `seed.py` repeats the shape of a disc item, which the store only reads. A change to that
  shape must change `fareguard.ops.seed_data.disc_item` too; its test reads the item back
  with `items.read_disc`.
