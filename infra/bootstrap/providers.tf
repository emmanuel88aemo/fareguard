# Credentials come from the default chain, for example AWS_PROFILE in the shell.
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "fareguard"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
