output "ledger_table_name" {
  description = "Name of the ledger table, the value of FAREGUARD_TABLE_NAME."
  value       = aws_dynamodb_table.ledger.name
}

output "ledger_table_arn" {
  description = "ARN of the ledger table."
  value       = aws_dynamodb_table.ledger.arn
}
