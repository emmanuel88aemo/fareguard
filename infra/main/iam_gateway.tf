# The role the gateway assumes to reach its target. It can invoke the tools
# function and do nothing else, as explained in
# docs/decisions/0005-gateway-with-iam-inbound-and-a-role-for-one-function.md.
data "aws_caller_identity" "current" {}

# Only the AgentCore service can assume the role, and only on behalf of a
# resource of this account.
data "aws_iam_policy_document" "gateway_trust" {
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

resource "aws_iam_role" "gateway" {
  name               = "${local.name_prefix}-gateway"
  description        = "Gateway: invokes the tools Lambda and nothing else."
  assume_role_policy = data.aws_iam_policy_document.gateway_trust.json
}

data "aws_iam_policy_document" "gateway" {
  # The unqualified ARN: the gateway invokes the function without a version or an alias.
  statement {
    sid       = "InvokeToolsFunction"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.tools.arn]
  }
}

resource "aws_iam_role_policy" "gateway" {
  name   = "invoke-tools-function"
  role   = aws_iam_role.gateway.name
  policy = data.aws_iam_policy_document.gateway.json
}

# Terraform owns the complete list of policies of the role: an inline policy
# or a managed policy attached by hand is removed on the next apply.
resource "aws_iam_role_policies_exclusive" "gateway" {
  role_name    = aws_iam_role.gateway.name
  policy_names = [aws_iam_role_policy.gateway.name]
}

resource "aws_iam_role_policy_attachments_exclusive" "gateway" {
  role_name   = aws_iam_role.gateway.name
  policy_arns = []
}

# IAM is eventually consistent: for some seconds after the role, its trust and
# its policy are created, AgentCore cannot assume the role yet. A target
# created in that window fails with "Gateway service is not authorized to
# perform AssumeRole on Gateway role", and only a second apply succeeds. The
# target waits for this pause instead, so a first apply from scratch works.
resource "time_sleep" "gateway_role_propagation" {
  create_duration = "20s"

  depends_on = [
    aws_iam_role.gateway,
    aws_iam_role_policy.gateway,
  ]
}
