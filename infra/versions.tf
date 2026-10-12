terraform {
  # >= 1.10 so an optional S3 backend can lock with use_lockfile (no DynamoDB
  # lock table needed). State is local by default and gitignored.
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.60"
    }
    vercel = {
      source  = "vercel/vercel"
      version = "~> 5.20"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.8"
    }
  }
}
