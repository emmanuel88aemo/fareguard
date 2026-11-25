output "ledger_table_name" {
  description = "Name of the ledger table, the value of FAREGUARD_TABLE_NAME."
  value       = aws_dynamodb_table.ledger.name
}

output "ledger_table_arn" {
  description = "ARN of the ledger table."
  value       = aws_dynamodb_table.ledger.arn
}

output "hook_log_group_name" {
  description = "Name of the log group of the hook Lambda."
  value       = aws_cloudwatch_log_group.hook.name
}

output "tools_log_group_name" {
  description = "Name of the log group of the tools Lambda."
  value       = aws_cloudwatch_log_group.tools.name
}

output "hook_lambda_role_arn" {
  description = "ARN of the role of the hook Lambda."
  value       = aws_iam_role.hook_lambda.arn
}

output "tools_lambda_role_arn" {
  description = "ARN of the role of the tools Lambda."
  value       = aws_iam_role.tools_lambda.arn
}

output "hook_function_name" {
  description = "Name of the hook Lambda function."
  value       = aws_lambda_function.hook.function_name
}

output "hook_function_arn" {
  description = "ARN of the hook Lambda function."
  value       = aws_lambda_function.hook.arn
}

output "tools_function_name" {
  description = "Name of the tools Lambda function."
  value       = aws_lambda_function.tools.function_name
}

output "tools_function_arn" {
  description = "ARN of the tools Lambda function."
  value       = aws_lambda_function.tools.arn
}

output "gateway_id" {
  description = "Id of the gateway."
  value       = aws_bedrockagentcore_gateway.tools.gateway_id
}

output "gateway_arn" {
  description = "ARN of the gateway."
  value       = aws_bedrockagentcore_gateway.tools.gateway_arn
}

output "gateway_url" {
  description = "URL of the MCP endpoint of the gateway."
  value       = aws_bedrockagentcore_gateway.tools.gateway_url
}

output "guardrail_id" {
  description = "Id of the guardrail, the value of FAREGUARD_GUARDRAIL_ID."
  value       = aws_bedrock_guardrail.hook.guardrail_id
}

output "guardrail_version" {
  description = "Published version of the guardrail the hook applies, the value of FAREGUARD_GUARDRAIL_VERSION."
  value       = aws_bedrock_guardrail_version.hook.version
}
