# The execution role of the harness: the identity under which the agent loop
# calls the model, the gateway and the hook function. The harness itself is
# created by scripts/create_harness.py, not by Terraform; see
# docs/decisions/0007-harness-with-a-pinned-model-and-no-built-in-tools.md.
#
# The statements below the first three are the ones the AgentCore
# documentation gives as the minimum policy of an execution role ("Security
# and access controls", sample execution role policy), each limited to a
# resource where the action allows it.
data "aws_region" "current" {}

locals {
  # A harness name allows no hyphen, so it is the name prefix with underscores.
  harness_name = replace(local.name_prefix, "-", "_")

  # The one model the harness may invoke: Amazon Nova 2 Lite, through the US
  # inference profile. fareguard.harness.config pins the same id.
  harness_model_id             = "amazon.nova-2-lite-v1:0"
  harness_inference_profile_id = "us.${local.harness_model_id}"

  # AgentCore writes the log of a harness to a log group of the runtime that
  # backs it. The runtime id is only known once the harness exists, so the
  # group cannot be created here or named exactly.
  harness_log_group_arn_prefix = "arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*"

  harness_workload_identity_directory_arn = "arn:aws:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default"
}

# Only the AgentCore service can assume the role, and only on behalf of a
# resource of this account.
data "aws_iam_policy_document" "harness_trust" {
  statement {
    sid     = "AgentCoreAssumesTheRole"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "harness" {
  name               = "${local.name_prefix}-harness"
  description        = "Harness: invokes one model, the gateway and the hook function, and writes its telemetry."
  assume_role_policy = data.aws_iam_policy_document.harness_trust.json
}

data "aws_iam_policy_document" "harness" {
  # The unqualified ARN: the harness is given the function without a version or an alias.
  statement {
    sid       = "InvokeHookFunction"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.hook.arn]
  }

  statement {
    sid       = "InvokeGateway"
    effect    = "Allow"
    actions   = ["bedrock-agentcore:InvokeGateway"]
    resources = [aws_bedrockagentcore_gateway.tools.gateway_arn]
  }

  # One model and no other. An inference profile routes a request to the
  # model in one of several regions, and Bedrock authorises both the profile
  # and the model in the region it chose. The region of the foundation model
  # is therefore a wildcard, and its ARN has no account.
  statement {
    sid     = "InvokeNova2Lite"
    effect  = "Allow"
    actions = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = [
      "arn:aws:bedrock:*::foundation-model/${local.harness_model_id}",
      "arn:aws:bedrock:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:inference-profile/${local.harness_inference_profile_id}",
    ]
  }

  # On the public network a harness pulls its managed container image from
  # Amazon ECR Public at the start of each session. Neither action supports
  # a resource: a token is not issued for one repository.
  statement {
    sid       = "GetTokenToPullTheManagedImage"
    effect    = "Allow"
    actions   = ["ecr-public:GetAuthorizationToken", "sts:GetServiceBearerToken"]
    resources = ["*"]
  }

  # The wildcard at the end of the prefix stands for the runtime id, which is
  # not known before the harness exists.
  statement {
    sid       = "CreateAndDescribeOwnLogGroup"
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:DescribeLogStreams"]
    resources = [local.harness_log_group_arn_prefix]
  }

  # DescribeLogGroups is authorised against the groups it may list, not one
  # group: a narrower resource makes the call fail. It reads names only.
  statement {
    sid       = "DescribeLogGroups"
    effect    = "Allow"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:*"]
  }

  statement {
    sid       = "WriteOwnLog"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${local.harness_log_group_arn_prefix}:log-stream:*"]
  }

  # PutResourcePolicy supports no resource. AgentCore uses it so that the
  # delivery of spans to CloudWatch Logs is allowed to write.
  statement {
    sid       = "PutLogResourcePolicy"
    effect    = "Allow"
    actions   = ["logs:PutResourcePolicy"]
    resources = ["*"]
  }

  # The X-Ray actions support no resource.
  statement {
    sid    = "WriteTraces"
    effect = "Allow"
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
      "xray:GetSamplingRules",
      "xray:GetSamplingTargets",
    ]
    resources = ["*"]
  }

  # PutMetricData supports no resource. The condition holds it to the
  # namespace of AgentCore.
  statement {
    sid       = "PublishMetrics"
    effect    = "Allow"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["bedrock-agentcore"]
    }
  }

  # The workload identity AgentCore creates for the harness is named
  # "harness_<harness name>-<suffix>"; the wildcard stands for the suffix.
  statement {
    sid    = "GetOwnWorkloadAccessToken"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:GetWorkloadAccessToken",
      "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
    ]
    resources = [
      local.harness_workload_identity_directory_arn,
      "${local.harness_workload_identity_directory_arn}/workload-identity/harness_${local.harness_name}-*",
    ]
  }
}

resource "aws_iam_role_policy" "harness" {
  name   = "model-gateway-hook-and-telemetry"
  role   = aws_iam_role.harness.name
  policy = data.aws_iam_policy_document.harness.json
}

# Terraform owns the complete list of policies of the role: an inline policy
# or a managed policy attached by hand is removed on the next apply.
resource "aws_iam_role_policies_exclusive" "harness" {
  role_name    = aws_iam_role.harness.name
  policy_names = [aws_iam_role_policy.harness.name]
}

resource "aws_iam_role_policy_attachments_exclusive" "harness" {
  role_name   = aws_iam_role.harness.name
  policy_arns = []
}
