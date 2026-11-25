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
| Hook Lambda function | `fareguard-<env>-hook` |
| Tools Lambda function | `fareguard-<env>-tools` |
| Role of the gateway | `fareguard-<env>-gateway` |
| AgentCore Gateway | `fareguard-<env>-gateway` |
| Target of the gateway, the tools function | `fareguard` |

It creates no guardrail or harness yet, so nothing calls the gateway or invokes the hook
function.

### The Lambda functions

| Function | Handler | Timeout |
|---|---|---|
| hook | `fareguard.handlers.hook_handler.lambda_handler` | 10 s |
| tools | `fareguard.handlers.tools_handler.lambda_handler` | 15 s |

Both run on `python3.12` and `arm64` with 256 MB, use the role and the log group listed
above, and receive the same environment variables:

| Environment variable | Value | Terraform variable | Default |
|---|---|---|---|
| `FAREGUARD_TABLE_NAME` | the name of the ledger table | none | |
| `FAREGUARD_MAX_USD_PER_DISC` | most that may be spent on one disc | `max_usd_per_disc` | `"1.00"` |
| `FAREGUARD_MONTHLY_CAP_USD` | most that may be spent in one month | `monthly_cap_usd` | `"5.00"` |
| `FAREGUARD_USD_PER_MINUTE` | price of one started minute | `usd_per_minute` | `"0.02"` |

The three limits are strings that hold a positive decimal with at most two decimals. To
change one, copy `main/terraform.tfvars.example` to `main/terraform.tfvars`, which Git
ignores, or pass `-var`.

### How the package is built

Both functions run the same zip. Terraform builds it with the `archive` provider on every
plan, from the directory `src/`, so the `fareguard` package is at the root of the zip.
`__pycache__` directories and `*.pyc` files are left out. The zip is written to
`infra/main/build/fareguard.zip`, which Git ignores, and its hash tells Terraform when the
code has changed: a plan made after a change under `src/` updates both functions.

The zip holds no dependency. The code needs only `boto3`, and the Python runtime of Lambda
provides it; see [decision record 0004](../docs/decisions/0004-lambda-package-without-dependencies.md).
There is no `pip install` and no build script: plan and apply are the whole deployment.

### The gateway

The gateway speaks MCP and authorises its callers with IAM (`AWS_IAM`): a caller signs its
request and needs `bedrock-agentcore:InvokeGateway` on this gateway. No role has that
permission yet. The reasons are in
[decision record 0005](../docs/decisions/0005-gateway-with-iam-inbound-and-a-role-for-one-function.md).

It has one target, named `fareguard`, which is the tools function, invoked with the
gateway's own role. A caller sees each tool as `fareguard___<tool>`; the hook and the tools
handler remove that prefix. The target declares exactly four tools:

| Tool | Arguments |
|---|---|
| `read_ledger` | none |
| `list_pending` | none |
| `request_approval` | `disc_id` |
| `launch_job` | `disc_id`, `approval_ref` |

Every argument is a required string. The descriptions say what each tool does and state no
rule or limit: the rules are enforced by the hook and by the tools, not by a description.

The function has no resource policy. The gateway and the function are in the same account,
where the policy of the gateway's role is enough to invoke it.

### What the roles may do

The two Lambda roles are trusted by `lambda.amazonaws.com` only. The gateway role is trusted
by `bedrock-agentcore.amazonaws.com` only, and only for resources of this account. Each has
one inline policy and no managed policy; Terraform removes any other policy it finds on them.

| Role | Actions | On |
|---|---|---|
| hook | `dynamodb:Query`, `dynamodb:GetItem` | the ledger table |
| hook | `logs:CreateLogStream`, `logs:PutLogEvents` | the streams of its own log group |
| tools | `dynamodb:Query`, `dynamodb:GetItem` | the ledger table |
| tools | `dynamodb:PutItem` | items of the ledger table whose partition key is `APPROVAL` or `EVENT` |
| tools | `dynamodb:UpdateItem` | items of the ledger table whose partition key is `DISC`, `APPROVAL` or `SPEND` |
| tools | `logs:CreateLogStream`, `logs:PutLogEvents` | the streams of its own log group |
| gateway | `lambda:InvokeFunction` | the tools function |

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

Read the plan. The first one creates 19 resources and destroys none. It also writes the zip
of the functions, so apply the plan from the same checkout that made it.

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

`validate` checks that the configuration is consistent. It does not build the zip, and it
does not check that AWS accepts the configuration, that the policies grant what the code
needs, that the functions start or that the gateway reaches the tools function; only a plan
and an apply show that.
