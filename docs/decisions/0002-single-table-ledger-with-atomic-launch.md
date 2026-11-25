# 0002. Single-table ledger with atomic launch

- Status: Accepted
- Date: 2026-11-25

## Context

The gate decides from a snapshot of the ledger: discs, approvals and spend. The gate runs
before a tool call and the tool runs afterwards, so two concurrent launches can both read
the same snapshot and both pass. An approval could then be used twice, or a cap exceeded,
without any single decision being wrong.

The agent may also call `request_approval` as often as it likes. Without a limit it can
flood the owner with requests for the same disc.

## Decision

**One DynamoDB table** with string keys `pk` and `sk` holds the whole ledger:

| `pk` | `sk` | Attributes |
|---|---|---|
| `DISC` | `<disc_id>` | `duration_seconds`, `spent_usd`, `pending_approval_ref` |
| `APPROVAL` | `<ref>` | `action`, `disc_id`, `approved_usd`, `status`, `consumed`, `requested_at` |
| `SPEND` | `<YYYY-MM>` | `spent_usd` |
| `EVENT` | `<ISO timestamp>#<id>` | `type`, `detail` |

Amounts are DynamoDB numbers, read and written as `Decimal`. Event timestamps are UTC and
fixed width, so the sort key orders events by time. Event ids are derived from the event
type and the approval ref, so a write is deterministic and the store needs no clock and no
random source.

**A launch is one transaction** of four writes, each with its own condition:

1. Approval: set `consumed`, only if it is approved, unconsumed, issued for `launch_job` and
   for this disc, and covers the estimate (R4).
2. Disc: add the estimate to `spent_usd`, only if the total stays within the per-disc cap (R2).
3. Month: add the estimate to `spent_usd`, only if the total stays within the monthly cap (R3).
4. Event: put `job_launched`, only if that key does not exist.

Either all four apply or none does. A failed condition is reported with the gate's rule id
and is never retried. The gate remains the first check; the transaction is what makes the
rules hold under concurrency.

**The monthly cap follows the UTC calendar month.** The month is derived from the time of
the launch in one function, never passed separately.

**A pending request marks its disc.** `pending_approval_ref` is set on the disc item in the
same transaction that creates the approval and writes an `approval_requested` event, and
only if the disc carries no mark. A condition can only read the item it writes, so "this
disc has no other pending request" must be a fact about one item.

**The store interface is narrow.** It cannot edit or delete an event, decide an approval or
change a limit. Every change of state writes an event in the same transaction.

## Alternatives considered

- **Check in the gate only.** Simple, but two concurrent launches defeat every cap.
- **Separate conditional writes, one per item.** A failure halfway leaves an approval
  consumed without spend recorded, or spend without an event.
- **Query for pending approvals, then put.** Keeps the table free of the marker, but two
  concurrent requests both see none pending and both succeed.
- **A separate marker item per disc.** Works, but adds an item type and a second key to keep
  in step with the disc; the disc item is already written by a launch.
- **One table per entity.** Transactions span tables too, so it buys nothing here and adds
  resources and IAM statements to manage.
- **Passing the month next to the time.** Two inputs that must agree will eventually
  disagree; a launch could then count against the wrong month.

## Consequences

- The caps and single use of an approval hold under concurrency, and each has a test that
  runs against every store implementation.
- Whoever decides an approval must remove `pending_approval_ref` from the disc in the same
  transaction that sets the status. If it is left behind, the disc can never be requested
  again: the failure is closed, but it is a failure.
- A launch at 23:59 UTC and one at 00:01 UTC count against different months, whatever the
  owner's local time is.
- Reads are not transactional: a snapshot is assembled from several queries, so it can be
  slightly stale. That is acceptable because the transaction, not the snapshot, enforces
  the rules.
- Approvals and events are never deleted, so reading all approvals grows with history. This
  will need an index or an archive before the table is large.
