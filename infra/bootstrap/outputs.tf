output "state_bucket_name" {
  description = "The bucket to name in infra/main/backend.hcl."
  value       = aws_s3_bucket.state.bucket
}
