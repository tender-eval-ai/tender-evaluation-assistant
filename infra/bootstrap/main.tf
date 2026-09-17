# One-time: the private S3 bucket that stores Terraform state for this project account.
# Runs inside the project account with the collaborator-accessible profile (dev-admin).
# Uses local state on purpose (it can't store its own state in a bucket that doesn't exist yet).

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

variable "profile" {
  description = "AWS CLI SSO profile with DevAdmin in the project account."
  type        = string
  default     = "dev-admin"
}

variable "account_id" {
  description = "Project account ID (tender-review-dev). Terraform refuses to run against any other account."
  type        = string
}

variable "region" {
  description = "Region for the state bucket."
  type        = string
}

variable "state_bucket_name" {
  description = "Globally unique name, e.g. tender-review-dev-tfstate-<account-id>."
  type        = string
}

provider "aws" {
  region              = var.region
  profile             = var.profile
  allowed_account_ids = [var.account_id]

  default_tags {
    tags = {
      managed-by = "terraform"
      project    = "tender-review"
      purpose    = "terraform-state"
    }
  }
}

resource "aws_s3_bucket" "state" {
  bucket = var.state_bucket_name

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

data "aws_iam_policy_document" "state" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.state.arn,
      "${aws_s3_bucket.state.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket     = aws_s3_bucket.state.id
  policy     = data.aws_iam_policy_document.state.json
  depends_on = [aws_s3_bucket_public_access_block.state]
}

output "state_bucket" {
  value = aws_s3_bucket.state.id
}
