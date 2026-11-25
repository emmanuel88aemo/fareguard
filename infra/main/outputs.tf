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
