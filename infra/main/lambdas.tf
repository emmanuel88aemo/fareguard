# One package for both functions: the content of src/, so that the fareguard
# package sits at the root of the zip. Nothing else is bundled; boto3 comes
# from the runtime, as explained in
# docs/decisions/0004-lambda-package-without-dependencies.md.
data "archive_file" "package" {
  type        = "zip"
  source_dir  = "${path.module}/../../src"
  output_path = "${path.module}/build/fareguard.zip"
  excludes    = ["**/__pycache__/**", "**/*.pyc"]

  # The same mode on every machine, so that the hash depends on the code only.
  output_file_mode = "0644"
}

locals {
  lambda_environment = {
    FAREGUARD_TABLE_NAME       = aws_dynamodb_table.ledger.name
    FAREGUARD_MAX_USD_PER_DISC = var.max_usd_per_disc
    FAREGUARD_MONTHLY_CAP_USD  = var.monthly_cap_usd
    FAREGUARD_USD_PER_MINUTE   = var.usd_per_minute
  }
}

resource "aws_lambda_function" "hook" {
  function_name = local.hook_function_name
  description   = "Answers the harness hook before every tool call with allow or deny."
  role          = aws_iam_role.hook_lambda.arn

  filename         = data.archive_file.package.output_path
  source_code_hash = data.archive_file.package.output_base64sha256
  handler          = "fareguard.handlers.hook_handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  memory_size      = 256
  timeout          = 10

  environment {
    variables = local.lambda_environment
  }

  # Text keeps each line the handler writes as it is: one JSON object per call.
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.hook.name
  }

  # The log group must exist first: the role cannot create one, and Lambda
  # must never create its own, which would have no retention.
  depends_on = [aws_cloudwatch_log_group.hook]
}

resource "aws_lambda_function" "tools" {
  function_name = local.tools_function_name
  description   = "Carries out the agent's tool calls against the ledger."
  role          = aws_iam_role.tools_lambda.arn

  filename         = data.archive_file.package.output_path
  source_code_hash = data.archive_file.package.output_base64sha256
  handler          = "fareguard.handlers.tools_handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  memory_size      = 256
  timeout          = 15

  environment {
    variables = local.lambda_environment
  }

  # Text keeps each line the handler writes as it is: one JSON object per call.
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.tools.name
  }

  # The log group must exist first: the role cannot create one, and Lambda
  # must never create its own, which would have no retention.
  depends_on = [aws_cloudwatch_log_group.tools]
}
