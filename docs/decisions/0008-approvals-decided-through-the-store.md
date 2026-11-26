# 0008. Approvals decided through the store

- Status: Accepted
- Date: 2026-11-25

## Context

Record 0002 kept the store interface narrow: it "cannot edit or delete an event, decide an
approval or change a limit", and a person was to decide approvals "through a separate
channel". That channel was never built, so a request stays pending for ever and no launch
can pass R4 outside a test that seeds an approved approval by hand.

Record 0002 also states what any such channel must do: remove `pending_approval_ref` from
the disc in the same transaction that sets the status, or the disc can never be requested
again. A second implementation of the ledger's writes, outside the store, would have to
repeat the table layout, the conditions and the event shape, and would not run under the
contract tests.

## Decision

**The store decides an approval.** `LedgerStore.decide_approval(ref, approved, at)` is part
of the contract and of both implementations. This supersedes one sentence of record 0002:
the store can now decide an approval. It still cannot edit or delete an event or change a
limit.

**One transaction of three conditional writes.** In DynamoDB:

| Write | Partition key | Condition |
|---|---|---|
| update the approval: set `status` to `approved` or `rejected` | `APPROVAL` | `status` is `pending`, `consumed` is false and `disc_id` is the one read |
| update the disc: remove `pending_approval_ref` | `DISC` | `pending_approval_ref` is exactly this ref |
| put an `approval_decided` event | `EVENT` | the item does not exist |

Either all three apply or none does. The approval is read once before the transaction, only
to learn its disc; the conditions, not that read, decide the outcome.

**A decision never consumes.** `consumed` stays false. An approved approval is consumed by
the launch that uses it, as before, so R4 and the single use of an approval are unchanged.
A rejected approval is unusable by its status.

**Refusals are named errors.** An unknown ref, an approval that is not pending or is already
consumed, and a disc that is not marked with this ref each raise their own error and write
nothing.

**The event is data the ledger already holds.** Its detail is the disc id, the approval ref
and the decision. It carries no text from a caller.

**The agent still has no tool for it.** `decide_approval` is called by a person. No tool
dispatches to it and the hook allows no tool of that name.

## Alternatives considered

- **A script that writes the three items itself.** Keeps the protocol as record 0002 left
  it, but duplicates the conditions outside the contract tests, which is where a forgotten
  `pending_approval_ref` would go unnoticed.
- **A second protocol for the person's side, on the same classes.** It states in types that
  the tools cannot decide, but the object the tools Lambda holds would still have the
  method. The separation that holds is the one below: no tool, and a role.
- **Consume on approval.** Then a launch could not tell an unused approval from a used one,
  and R4 would have to change.
- **Take the disc as an argument.** The caller could then name a disc the approval was not
  issued for. The disc is read from the approval instead.

## Consequences

- The object the tools Lambda holds now has a method that decides an approval. The agent
  cannot reach it: it can call the four tools, and none of them leads there. This is a
  property of the code and its tests, like the ones record 0003 lists.
- At the IAM level nothing changes for the tools role: record 0003 already notes that it
  could set `status` with `UpdateItem`. The three writes and the read use actions and
  partition keys that role already has, so no policy changes with this record.
- Record 0003 still holds: whoever decides an approval needs a role of their own. That role
  and the command a person runs are not built yet.
- A disc is free for a new request after either decision (R6).
- A decision cannot be undone or changed: the approval is no longer pending.
