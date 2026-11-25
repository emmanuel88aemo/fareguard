# The role of the hook Lambda. The hook reads the ledger to decide; it never
# writes. It applies one guardrail to the text it screens.
resource "aws_iam_role" "hook_lambda" {
  name               = "${local.name_prefix}-hook-lambda"
  description        = "Hook Lambda: reads the ledger, applies the guardrail and writes its own log."
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

data "aws_iam_policy_document" "hook_lambda" {
  statement {
    sid       = "ReadLedger"
    effect    = "Allow"
    actions   = ["dynamodb:Query", "dynamodb:GetItem"]
    resources = [aws_dynamodb_table.ledger.arn]
  }

  # This guardrail and no other. The ARN of a guardrail holds no version: the
  # function chooses the published version by its number.
  statement {
    sid       = "ApplyGuardrail"
    effect    = "Allow"
    actions   = ["bedrock:ApplyGuardrail"]
    resources = [aws_bedrock_guardrail.hook.guardrail_arn]
  }

  statement {
    sid     = "WriteOwnLog"
    effect  = "Allow"
    actions = ["logs:CreateLogStream", "logs:PutLogEvents"]
    # The wildcard stands for the log streams of this one log group. Lambda
    # names a stream per execution environment, so the names cannot be listed.
    resources = ["${aws_cloudwatch_log_group.hook.arn}:*"]
  }
}

resource "aws_iam_role_policy" "hook_lambda" {
  name   = "ledger-read-guardrail-and-own-log"
  role   = aws_iam_role.hook_lambda.name
  policy = data.aws_iam_policy_document.hook_lambda.json
}

# Terraform owns the complete list of policies of the role: an inline policy
# or a managed policy attached by hand is removed on the next apply.
resource "aws_iam_role_policies_exclusive" "hook_lambda" {
  role_name    = aws_iam_role.hook_lambda.name
  policy_names = [aws_iam_role_policy.hook_lambda.name]
}

resource "aws_iam_role_policy_attachments_exclusive" "hook_lambda" {
  role_name   = aws_iam_role.hook_lambda.name
  policy_arns = []
}
