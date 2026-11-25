# Both roles can be assumed by the Lambda service and by nothing else.
data "aws_iam_policy_document" "lambda_trust" {
  statement {
    sid     = "LambdaAssumesTheRole"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}
