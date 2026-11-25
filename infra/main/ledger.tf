# The single table of the ledger. Its keys and item types are described in
# docs/decisions/0002-single-table-ledger-with-atomic-launch.md.
resource "aws_dynamodb_table" "ledger" {
  name         = "${local.name_prefix}-ledger"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  # Encrypts with the AWS managed key for DynamoDB instead of the AWS owned one.
  server_side_encryption {
    enabled = true
  }
}
