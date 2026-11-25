variable "region" {
  description = "AWS region of every resource in this stack."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name, used in resource names and in the Environment tag."
  type        = string
  default     = "dev"

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,9}$", var.environment))
    error_message = "The environment must be 2 to 10 lower-case letters or digits, starting with a letter."
  }
}
