# The log groups are created here, before the functions exist, so that each
# role can be limited to its own group and needs no logs:CreateLogGroup.
resource "aws_cloudwatch_log_group" "hook" {
  name              = "/aws/lambda/${local.hook_function_name}"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "tools" {
  name              = "/aws/lambda/${local.tools_function_name}"
  retention_in_days = 14
}
