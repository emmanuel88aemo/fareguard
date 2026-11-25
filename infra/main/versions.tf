terraform {
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.74"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
  }

  # Partial configuration: the bucket, the key and the region are passed with
  # -backend-config=backend.hcl, which Git ignores. See backend.hcl.example.
  backend "s3" {
    encrypt      = true
    use_lockfile = true
  }
}
