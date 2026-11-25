variable "region" {
  description = "AWS region of the state bucket."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name, used in the Environment tag."
  type        = string
  default     = "dev"

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,9}$", var.environment))
    error_message = "The environment must be 2 to 10 lower-case letters or digits, starting with a letter."
  }
}

variable "state_bucket_name" {
  description = "Name of the S3 bucket that holds the Terraform state. Bucket names are global, so it is chosen per account and never committed."
  type        = string

  validation {
    condition     = can(regex("^fareguard-[a-z0-9][a-z0-9-]{1,51}[a-z0-9]$", var.state_bucket_name))
    error_message = "The bucket name must start with \"fareguard-\" and continue with 3 to 53 lower-case letters, digits or hyphens, ending in a letter or digit."
  }
}
