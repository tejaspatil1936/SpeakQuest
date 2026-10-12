# S3 bucket for audio, transcripts and results (system design §7).
# Public access fully blocked; browsers only ever use short-lived presigned
# URLs. force_destroy so `terraform destroy` is never blocked by objects.

resource "random_id" "suffix" {
  byte_length = 3
}

resource "aws_s3_bucket" "audio" {
  bucket        = "${var.name_prefix}-${random_id.suffix.hex}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "audio" {
  bucket                  = aws_s3_bucket.audio.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "audio" {
  bucket = aws_s3_bucket.audio.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# SSE-S3 (AES256): no customer-managed KMS key, so nothing with a deletion
# window or monthly fee (§8.1 rule 5).
resource "aws_s3_bucket_server_side_encryption_configuration" "audio" {
  bucket = aws_s3_bucket.audio.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# Deny anything that isn't TLS.
data "aws_iam_policy_document" "tls_only" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.audio.arn,
      "${aws_s3_bucket.audio.arn}/*",
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

resource "aws_s3_bucket_policy" "audio" {
  bucket     = aws_s3_bucket.audio.id
  policy     = data.aws_iam_policy_document.tls_only.json
  depends_on = [aws_s3_bucket_public_access_block.audio]
}

# Presigned PUTs and GETs from the browser need CORS on the bucket itself.
resource "aws_s3_bucket_cors_configuration" "audio" {
  bucket = aws_s3_bucket.audio.id
  cors_rule {
    allowed_methods = ["PUT", "GET", "HEAD"]
    allowed_origins = var.allowed_origins
    allowed_headers = ["content-type", "content-length"]
    expose_headers  = ["etag", "content-length", "content-type"]
    max_age_seconds = 600
  }
}

# Recordings expire after 7 days, intermediate audio after 1 (§7, §11).
resource "aws_s3_bucket_lifecycle_configuration" "audio" {
  bucket = aws_s3_bucket.audio.id

  rule {
    id     = "uploads-7d"
    status = "Enabled"
    filter {
      prefix = "uploads/"
    }
    expiration {
      days = 7
    }
  }

  rule {
    id     = "work-1d"
    status = "Enabled"
    filter {
      prefix = "work/"
    }
    expiration {
      days = 1
    }
  }

  rule {
    id     = "transcripts-7d"
    status = "Enabled"
    filter {
      prefix = "transcripts/"
    }
    expiration {
      days = 7
    }
  }

  rule {
    id     = "results-14d"
    status = "Enabled"
    filter {
      prefix = "results/"
    }
    expiration {
      days = 14
    }
  }

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}
