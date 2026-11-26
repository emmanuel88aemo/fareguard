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
| Bedrock Guardrail and one published version of it | `fareguard-<env>-guardrail` |
| Execution role of the harness | `fareguard-<env>-harness` |

It does not create the harness. A person creates it with `scripts/create_harness.py`, from
the outputs of this stack; see [`harness/README.md`](../harness/README.md). Until then
nothing calls the gateway or invokes the hook function.

### The Lambda functions

| Function | Handler | Timeout |
|---|---|---|
| hook | `fareguard.handlers.hook_handler.lambda_handler` | 10 s |
| tools | `fareguard.handlers.tools_handler.lambda_handler` | 15 s |

Both run on `python3.12` and `arm64` with 256 MB, use the role and the log group listed
above, and receive these environment variables:

| Environment variable | Value | Terraform variable | Default |
|---|---|---|---|
| `FAREGUARD_TABLE_NAME` | the name of the ledger table | none | |
| `FAREGUARD_MAX_USD_PER_DISC` | most that may be spent on one disc | `max_usd_per_disc` | `"1.00"` |
| `FAREGUARD_MONTHLY_CAP_USD` | most that may be spent in one month | `monthly_cap_usd` | `"5.00"` |
| `FAREGUARD_USD_PER_MINUTE` | price of one started minute | `usd_per_minute` | `"0.02"` |

The three limits are strings that hold a positive decimal with at most two decimals. To
change one, copy `main/terraform.tfvars.example` to `main/terraform.tfvars`, which Git
ignores, or pass `-var`.

The hook function receives two more, which the tools function does not:

| Environment variable | Value |
|---|---|
| `FAREGUARD_GUARDRAIL_ID` | the id of the guardrail |
| `FAREGUARD_GUARDRAIL_VERSION` | the number of its published version |

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
request and needs `bedrock-agentcore:InvokeGateway` on this gateway. The execution role of
the harness has that permission and no other role does. The reasons are in
[decision record 0005](../docs/decisions/0005-gateway-with-iam-inbound-and-a-role-for-one-function.md).

It has one target, named `fareguard`, which is the tools function, invoked with the
gateway's own role. A caller sees each tool as `fareguard___<tool>`, with three underscores;
the hook and the tools handler remove that prefix. A real call through the deployed gateway
confirmed the format: the tools are listed and called under those names. The target declares
exactly four tools:

| Tool | Arguments |
|---|---|
| `read_ledger` | none |
| `list_pending` | none |
| `request_approval` | `disc_id` |
| `launch_job` | `disc_id`, `approval_ref` |

Every argument is a required string. The descriptions say what each tool does and state no
rule or limit: the rules are enforced by the hook and by the tools, not by a description.

The target is created 20 seconds after the gateway's role and its policy. Without that
pause a first apply fails, because AgentCore cannot assume a role that IAM has only just
created.

The function has no resource policy. The gateway and the function are in the same account,
where the policy of the gateway's role is enough to invoke it.

### The guardrail

The hook function applies the guardrail, through the `ApplyGuardrail` API, to what a caller
sends (`before_invocation`) and to what a tool returns (`after_tool_call`). It is not
attached to a harness or to a model, and no rule depends on it: see
[decision record 0006](../docs/decisions/0006-guardrail-applied-by-the-hook.md).

| Policy | Setting |
|---|---|
| Content filter | `PROMPT_ATTACK`, strength `HIGH` on input, blocking |
| Blocked messages | one fixed sentence; the hook does not pass it on |

The guardrail does one thing: it filters prompt-injection attacks. It has no denied topic.
One was tried, narrowed and then removed, because it stopped the agent's own requests for
an approval and its launches with one, and still missed polite requests to change a rule
([decision record 0011](../docs/decisions/0011-guardrail-with-the-prompt-attack-filter-only.md)).
Nothing was lost with it: the spending limits and the approval requirement are enforced by
the hook, the tools and IAM (R2, R3 and R4), not by the guardrail.

The filter is not expected to catch an instruction hidden in what a tool returns, such as
the planted event of stress case A2. That case is answered by the system prompt, which
treats ledger content as data, and by R4, which denies a launch with no approval.

The hook applies a published version by its number, never the working draft. A version
does not follow its guardrail, so any change to the guardrail publishes a new version in
the same apply, gives its number to the hook function and only then deletes the old one.
A guardrail keeps at most 20 versions; this stack keeps one.

Each call is billed per 1,000 characters of text and per policy. Record 0006 has the
figures for two policies; with the filter alone a call costs half of that.

### What the roles may do

The two Lambda roles are trusted by `lambda.amazonaws.com` only. The gateway role and
the execution role of the harness are trusted by `bedrock-agentcore.amazonaws.com` only, and
only for resources of this account. Each has one inline policy and no managed policy; Terraform removes any other policy it finds on them.

| Role | Actions | On |
|---|---|---|
| hook | `dynamodb:Query`, `dynamodb:GetItem` | the ledger table |
| hook | `bedrock:ApplyGuardrail` | the guardrail |
| hook | `logs:CreateLogStream`, `logs:PutLogEvents` | the streams of its own log group |
| tools | `dynamodb:Query`, `dynamodb:GetItem` | the ledger table |
| tools | `dynamodb:PutItem` | items of the ledger table whose partition key is `APPROVAL` or `EVENT` |
| tools | `dynamodb:UpdateItem` | items of the ledger table whose partition key is `DISC`, `APPROVAL` or `SPEND` |
| tools | `logs:CreateLogStream`, `logs:PutLogEvents` | the streams of its own log group |
| gateway | `lambda:InvokeFunction` | the tools function |
| harness | `lambda:InvokeFunction` | the hook function |
| harness | `bedrock-agentcore:InvokeGateway` | the gateway |
| harness | `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream` | Amazon Nova 2 Lite: the foundation model in any region and its US inference profile in this account |
| harness | what AgentCore needs to run a harness | see below |

### The execution role of the harness

The harness assumes this role to call the model, the gateway and the hook function. The
first three rows above are what the agent needs. The rest is the minimum policy the
AgentCore documentation gives for an execution role ("Security and access controls", sample
execution role policy), with each statement limited to a resource where the action allows
it:

| Statement | Actions | On |
|---|---|---|
| `CreateAndDescribeOwnLogGroup` | `logs:CreateLogGroup`, `logs:DescribeLogStreams` | log groups named `/aws/bedrock-agentcore/runtimes/*` |
| `WriteOwnLog` | `logs:CreateLogStream`, `logs:PutLogEvents` | the streams of those log groups |
| `GetOwnWorkloadAccessToken` | `bedrock-agentcore:GetWorkloadAccessToken`, `GetWorkloadAccessTokenForJWT` | the default workload identity directory and the identities named `harness_fareguard_<env>-*` |

The log group of a harness is named after the runtime that backs it, whose id exists only
once the harness is created. Terraform therefore does not create that log group and cannot
name it exactly: AgentCore creates it, with no retention period set.

Six statements are not limited to one resource:

| Statement | Actions | Resource | Why it is a wildcard |
|---|---|---|---|
| `InvokeNova2Lite` | the two `bedrock:Invoke*` actions | `foundation-model/amazon.nova-2-lite-v1:0` in region `*` | An inference profile sends a request to the model in one of several regions, and Bedrock authorises the model in the region it chose. The model is still one model. |
| `GetTokenToPullTheManagedImage` | `ecr-public:GetAuthorizationToken`, `sts:GetServiceBearerToken` | `*` | A harness pulls its managed container image from Amazon ECR Public at the start of each session. A token is not issued for one repository, so neither action supports a resource. |
| `DescribeLogGroups` | `logs:DescribeLogGroups` | every log group of this account and region | The action is authorised against the groups it may list. It reads names only. |
| `PutLogResourcePolicy` | `logs:PutResourcePolicy` | `*` | The action supports no resource. AgentCore uses it to let the delivery of spans write to CloudWatch Logs. It is the widest grant of the role: a resource policy of CloudWatch Logs can let an AWS service write to log groups of the account. |
| `WriteTraces` | `xray:PutTraceSegments`, `PutTelemetryRecords`, `GetSamplingRules`, `GetSamplingTargets` | `*` | The X-Ray actions support no resource. |
| `PublishMetrics` | `cloudwatch:PutMetricData` | `*`, only in the namespace `bedrock-agentcore` | The action supports no resource; the condition on the namespace is the limit. |

Which of these a harness fails without has not been tested: the stack has not been applied
with this role, and no harness has been created.

The role is not a boundary around the model's instructions: whoever may call
`InvokeHarness` can replace the model, the prompt and the tools for one call. It is a
boundary around what any such call can reach: one model, one gateway, one function. See
[decision record 0007](../docs/decisions/0007-harness-with-a-pinned-model-and-no-built-in-tools.md).

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

Read the plan. The first one creates 26 resources and destroys none. It also writes the zip
of the functions, so apply the plan from the same checkout that made it.

On a stack that was applied before the guardrail existed, the plan that adds it replaces
the inline policy of the hook role, because the policy has a new name. Expect that one
resource to be destroyed and created again, and no other to be destroyed.

On a stack that was applied before the execution role of the harness existed, the plan adds
the role, its policy and the two resources that keep its list of policies exclusive. It also
updates both Lambda functions, because the zip now holds the module `fareguard.harness`,
which neither function imports.

## 4. Apply

```bash
terraform apply tfplan
terraform output
```

`terraform apply tfplan` applies exactly the plan you read and asks no question.

The outputs `harness_name`, `harness_execution_role_arn`, `gateway_arn` and
`hook_function_arn` are what `scripts/create_harness.py` reads to create the harness.

## 5. Destroy

If a harness was created, delete it first: it is not in the state, and it would keep using
a role and a gateway that no longer exist. See [`harness/README.md`](../harness/README.md).

Then `main/`. **This deletes the ledger table and everything in it.**

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
needs, that the functions start, that the gateway reaches the tools function, that the
guardrail blocks anything or that AgentCore can run a harness with the execution role; only
a plan and an apply show that.
