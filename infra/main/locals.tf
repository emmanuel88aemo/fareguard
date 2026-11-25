locals {
  name_prefix = "fareguard-${var.environment}"

  # The names the Lambda functions will have. Lambda writes to the log group
  # /aws/lambda/<function name> unless told otherwise, so the log groups and
  # the functions must agree on them.
  hook_function_name  = "${local.name_prefix}-hook"
  tools_function_name = "${local.name_prefix}-tools"
}
