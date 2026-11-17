resource "aws_s3_bucket" "statements" {
  bucket = var.bucket_name
  tags   = var.tags
}

resource "aws_s3_bucket_public_access_block" "statements" {
  bucket = aws_s3_bucket.statements.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "statements" {
  bucket = aws_s3_bucket.statements.id

  rule {
    apply_server_side_encryption_by_default {
      # XS-COMP-06 / D13: the customer-managed key when one is given (prod, and dev once invited
      # testers arrive); AWS-managed keys only while dev holds the owner's data alone.
      sse_algorithm     = var.kms_key_arn == null ? "AES256" : "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = var.kms_key_arn != null # fewer KMS calls per object
  }
}

# XS-COMP-06: deny every request made without TLS (aws:SecureTransport = false), bucket and objects.
resource "aws_s3_bucket_policy" "tls_only" {
  bucket = aws_s3_bucket.statements.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.statements.arn, "${aws_s3_bucket.statements.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.statements]
}

# XS-COMP-06: versioning keeps a recovery path, but old versions of a deleted statement must not
# outlive the deletion promise (XS-DEL-07), so noncurrent versions expire after 7 days.
resource "aws_s3_bucket_lifecycle_configuration" "statements" {
  bucket = aws_s3_bucket.statements.id

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 7
    }

    # XS-DEL-07: with the last version gone, drop the delete marker too.
    expiration {
      expired_object_delete_marker = true
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.statements]
}

# Statement PDFs/CSVs/images are financial documents (CLAUDE.md's PII/log-hygiene concern applies
# to data at rest too) — versioning gives a recovery path if the Ledger's overwrite-on-duplicate
# flow (REQ-STMT-05) or an accidental delete removes something still needed.
resource "aws_s3_bucket_versioning" "statements" {
  bucket = aws_s3_bucket.statements.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Required for the direct-to-S3 browser PUT (Step 2 of the upload flow) to work against a real
# bucket — real S3 enforces CORS on cross-origin requests; LocalStack's S3 emulation did not, so
# this had no equivalent before.
resource "aws_s3_bucket_cors_configuration" "statements" {
  bucket = aws_s3_bucket.statements.id

  cors_rule {
    allowed_methods = ["PUT"]
    allowed_origins = var.cors_allowed_origins
    allowed_headers = ["*"]
    max_age_seconds = 3000
  }
}

# XS-COMP-07: GuardDuty reads bucket events through EventBridge when the malware scan is on. Ingest
# reads the scan tag when it opens a file (IN-IMP-03); nothing is triggered by an upload.
resource "aws_s3_bucket_notification" "statement_upload" {
  bucket      = aws_s3_bucket.statements.id
  eventbridge = var.malware_scan_enabled
}
