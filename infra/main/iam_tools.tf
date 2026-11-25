# The role of the tools Lambda, the only writer of the ledger. What it may
# write is limited by partition key, as explained in
# docs/decisions/0003-remote-state-in-s3-and-a-tools-role-limited-by-partition-key.md.
#
# The store writes only through TransactWriteItems. DynamoDB authorises each
# item of a transaction with the action of that item (PutItem or UpdateItem)
# and its partition key, so the conditions below apply to every write.
#
# Not granted, on purpose: DeleteItem, BatchWriteItem, Scan, ConditionCheckItem
# and the PartiQL actions.
resource "aws_iam_role" "tools_lambda" {
  name               = "${local.name_prefix}-tools-lambda"
  description        = "Tools Lambda: reads the ledger, writes it by partition key and writes its own log."
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

data "aws_iam_policy_document" "tools_lambda" {
  statement {
    sid       = "ReadLedger"
    effect    = "Allow"
    actions   = ["dynamodb:Query", "dynamodb:GetItem"]
    resources = [aws_dynamodb_table.ledger.arn]
  }

  # A new approval request and every event. No update is allowed on EVENT.
  statement {
    sid       = "PutApprovalsAndEvents"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.ledger.arn]

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "dynamodb:LeadingKeys"
      values   = ["APPROVAL", "EVENT"]
    }

    # ForAllValues is true when the key is absent. This makes its absence a refusal.
    condition {
      test     = "Null"
      variable = "dynamodb:LeadingKeys"
      values   = ["false"]
    }
  }

  # The mark and the spend of a disc, the consumption of an approval and the
  # spend of a month.
  statement {
    sid       = "UpdateDiscsApprovalsAndSpend"
    effect    = "Allow"
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.ledger.arn]

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "dynamodb:LeadingKeys"
      values   = ["DISC", "APPROVAL", "SPEND"]
    }

    condition {
      test     = "Null"
      variable = "dynamodb:LeadingKeys"
      values   = ["false"]
    }
  }

  statement {
    sid     = "WriteOwnLog"
    effect  = "Allow"
    actions = ["logs:CreateLogStream", "logs:PutLogEvents"]
    # The wildcard stands for the log streams of this one log group. Lambda
    # names a stream per execution environment, so the names cannot be listed.
    resources = ["${aws_cloudwatch_log_group.tools.arn}:*"]
  }
}

resource "aws_iam_role_policy" "tools_lambda" {
  name   = "ledger-write-by-partition-key-and-own-log"
  role   = aws_iam_role.tools_lambda.name
  policy = data.aws_iam_policy_document.tools_lambda.json
}

# Terraform owns the complete list of policies of the role: an inline policy
# or a managed policy attached by hand is removed on the next apply.
resource "aws_iam_role_policies_exclusive" "tools_lambda" {
  role_name    = aws_iam_role.tools_lambda.name
  policy_names = [aws_iam_role_policy.tools_lambda.name]
}

resource "aws_iam_role_policy_attachments_exclusive" "tools_lambda" {
  role_name   = aws_iam_role.tools_lambda.name
  policy_arns = []
}
