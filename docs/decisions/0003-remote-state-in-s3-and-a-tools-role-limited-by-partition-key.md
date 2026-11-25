# 0003. Remote state in S3 and a tools role limited by partition key

- Status: Accepted
- Date: 2026-11-25

## Context

The first Terraform code needs somewhere to keep its state. State describes everything that
exists in AWS and names the account, so it cannot live in this public repository, and a
state that exists on one laptop only is lost with it.

The tools Lambda is the only component that writes to the ledger. Record 0002 made the store
interface narrow: it cannot edit or delete an event, and it cannot delete anything. That is
a property of the Python code. Record 0001 asks for mechanisms the model cannot reach, and
IAM is one of them: a bug or a change in the code should not be able to widen what the role
can do to the ledger.

## Decision

**State is kept in one S3 bucket, with two Terraform directories.**

- `infra/bootstrap` creates only that bucket and keeps its own state in a local file. The
  bucket is versioned, encrypted, closed to the public, owned by the bucket owner and refuses
  requests without TLS.
- `infra/main` holds everything else and keeps its state in the bucket. The lock is the S3
  lock file (`use_lockfile`), so no DynamoDB lock table exists.
- The backend is configured partially: the bucket, the key and the region come from
  `backend.hcl`, which is not committed. A `backend.hcl.example` sits next to it. The bucket
  name is given in `terraform.tfvars`, also not committed, with its own example.
- No account id appears in any file. ARNs are taken from the resources themselves.

**The tools role is limited by partition key.** Its policy allows, on the ledger table only:

| Action | Items |
|---|---|
| `dynamodb:Query`, `dynamodb:GetItem` | any |
| `dynamodb:PutItem` | partition key `APPROVAL` or `EVENT` |
| `dynamodb:UpdateItem` | partition key `DISC`, `APPROVAL` or `SPEND` |

The two write statements use the condition key `dynamodb:LeadingKeys` with
`ForAllValues:StringEquals`, and a `Null` condition that requires the key to be present.
`ForAllValues` is true when the key is absent, so without the `Null` condition a request
that carries no partition key would be allowed instead of refused.

The store writes only through `TransactWriteItems`. DynamoDB authorises each item of a
transaction separately, with the action of that item (`PutItem` or `UpdateItem` here) and
its partition key, so the conditions apply to every write of every transaction. There is no
IAM action for the transaction itself.

These are the writes the store performs, and each is allowed by exactly one statement:

| Operation | Write | Partition key |
|---|---|---|
| `create_approval_request` | put the approval | `APPROVAL` |
| | update the disc: set `pending_approval_ref` | `DISC` |
| | put the event | `EVENT` |
| `record_launch` | update the approval: set `consumed` | `APPROVAL` |
| | update the disc: add to `spent_usd` | `DISC` |
| | update the month: add to `spent_usd` | `SPEND` |
| | put the event | `EVENT` |

`DeleteItem`, `BatchWriteItem`, `Scan`, `ConditionCheckItem` and the PartiQL actions are not
granted. The hook role may only `Query` and `GetItem`.

Each role has one inline policy, and Terraform owns the complete list of inline and managed
policies of the role, so a policy attached by hand is removed on the next apply.

## Alternatives considered

- **Local state for everything.** Nothing to create first, but the state is lost with the
  laptop and cannot be used from CI.
- **A DynamoDB table for the lock.** It was the only way before Terraform 1.10. The S3 lock
  file needs no second resource and no second set of permissions.
- **The bucket in the same directory as everything else.** A backend cannot be stored in a
  bucket that the same configuration creates, without a two-step migration at first use.
- **Write access to the whole table.** Shorter, but then only the Python code stands between
  a bug and an edited event.
- **Limiting attributes too, with `dynamodb:Attributes`.** That key lists every attribute a
  request names, including those its condition expression only reads. The launch reads
  `status` in order to check it, so a policy cannot allow that and still forbid writing
  `status`. It would also forbid the `ALL_OLD` return value the store uses to tell an
  unknown disc from a cap that was reached.
- **One table per entity, with a policy per table.** Record 0002 chose one table. Partition
  keys give the same separation inside it.

## Consequences

- An event can be put but never updated or deleted by the tools role, and no item of any
  kind can be deleted by it. This holds whatever the code does.
- **IAM does not see attributes or condition expressions.** At the IAM level the tools role
  could still:
  - replace an existing event or approval with `PutItem`, because a put without a condition
    overwrites. Only the store's `attribute_not_exists(pk)` condition prevents it;
  - set `status` to `approved` on an approval, or create a disc, with `UpdateItem`. Only the
    store's code does not do so.

  These remain properties of the code and its tests. The agent cannot reach them: it can
  call the tools, not the role.
- A new kind of write in the store needs a change to the policy in the same pull request, or
  it fails in AWS with `AccessDenied` although the tests pass. moto does not evaluate IAM.
- Whoever decides an approval needs a different role. The tools role cannot be reused for
  it without widening it.
- The bootstrap state is a local file. If it is lost, the bucket must be imported before
  the bootstrap directory can be applied again. The bucket itself, and the state inside it,
  are not affected.
- The state bucket is the one resource whose name does not come from
  `fareguard-<env>-<component>`: bucket names are global, so the name is chosen per account
  and only has to start with `fareguard-`.
