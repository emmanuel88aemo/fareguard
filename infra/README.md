# Infrastructure

Everything Fareguard has in AWS is declared here with Terraform. The reasons for this layout
are in [decision record 0003](../docs/decisions/0003-remote-state-in-s3-and-a-tools-role-limited-by-partition-key.md).

No workflow plans or applies this yet: a person runs the commands below.

## What each directory creates

| Directory | State | Creates |
|---|---|---|
| `bootstrap/` | Local file, not committed | The S3 bucket that holds the state of `main/`: versioned, encrypted, closed to the public, bucket-owner-enforced, TLS only |
| `main/` | In that bucket, locked with the S3 lock file | Everything else, listed below |

`main/` creates, for the environment `<env>` (default `dev`):

| Resource | Name |
|---|---|
| DynamoDB table of the ledger | `fareguard-<env>-ledger` |
| Log group of the hook Lambda, 14 days | `/aws/lambda/fareguard-<env>-hook` |
| Log group of the tools Lambda, 14 days | `/aws/lambda/fareguard-<env>-tools` |
| Role of the hook Lambda | `fareguard-<env>-hook-lambda` |
| Role of the tools Lambda | `fareguard-<env>-tools-lambda` |

It creates no Lambda function, gateway, guardrail or harness yet.

### What the roles may do

Both roles are trusted by `lambda.amazonaws.com` only. Each has one inline policy and no
managed policy; Terraform removes any other policy it finds on them.

| Role | Actions | On |
|---|---|---|
| hook | `dynamodb:Query`, `dynamodb:GetItem` | the ledger table |
| hook | `logs:CreateLogStream`, `logs:PutLogEvents` | the streams of its own log group |
| tools | `dynamodb:Query`, `dynamodb:GetItem` | the ledger table |
| tools | `dynamodb:PutItem` | items of the ledger table whose partition key is `APPROVAL` or `EVENT` |
| tools | `dynamodb:UpdateItem` | items of the ledger table whose partition key is `DISC`, `APPROVAL` or `SPEND` |
| tools | `logs:CreateLogStream`, `logs:PutLogEvents` | the streams of its own log group |

## Before you start

- Terraform 1.10 or later. CI uses the version pinned in `.github/workflows/ci.yml`.
- AWS credentials from the default chain, for example `export AWS_PROFILE=<your profile>`.
  No profile name is written in any file here.
- Two files hold what is specific to your account. Git ignores both, and each has a
  committed example next to it:
  - `bootstrap/terraform.tfvars`: the name of the state bucket.
  - `main/backend.hcl`: where `main/` finds its state.

The region defaults to `us-east-1` and the environment to `dev`. To change one, set it in
`terraform.tfvars` (bootstrap) or pass `-var`, for example `-var environment=prod`. Another
environment of `main/` also needs its own `key` in `backend.hcl`.

## 1. Bootstrap the state bucket

Once per account.

```bash
cd infra/bootstrap
cp terraform.tfvars.example terraform.tfvars   # then edit: choose the bucket name
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

The bucket name must start with `fareguard-`. Bucket names are global, so add something
only your account would use.

The state of this directory is the file `infra/bootstrap/terraform.tfstate`. Keep it: without
it Terraform no longer knows that it created the bucket, and the bucket has to be imported
with `terraform import aws_s3_bucket.state <bucket name>` (and likewise for its settings)
before this directory can be applied again.

## 2. Initialise `main/` with the backend configuration

```bash
cd infra/main
cp backend.hcl.example backend.hcl   # then edit: the bucket name from step 1
terraform init -backend-config=backend.hcl
```

After changing `backend.hcl`, run `terraform init -reconfigure -backend-config=backend.hcl`.

## 3. Plan

```bash
terraform plan -out=tfplan
```

Read the plan. The first one creates 11 resources and destroys none.

## 4. Apply

```bash
terraform apply tfplan
terraform output
```

`terraform apply tfplan` applies exactly the plan you read and asks no question.

## 5. Destroy

`main/` first. **This deletes the ledger table and everything in it.**

```bash
cd infra/main
terraform plan -destroy -out=tfplan
terraform apply tfplan
```

Then, only if the account should keep nothing, the state bucket:

```bash
cd infra/bootstrap
terraform plan -destroy -out=tfplan
terraform apply tfplan
```

The second destroy fails while the bucket holds any object or any old version of one, and
that is intended: the bucket is not created with `force_destroy`. Empty it first, including
all versions (the "Empty" action of the S3 console does both), then run the two commands again.

## Checks that need no AWS account

CI runs these on every pull request, without credentials:

```bash
terraform fmt -check -recursive
cd infra/bootstrap && terraform init -backend=false && terraform validate
cd ../main && terraform init -backend=false && terraform validate
```

`validate` checks that the configuration is consistent. It does not check that AWS accepts
it or that the policies grant what the code needs; only a plan and an apply show that.
