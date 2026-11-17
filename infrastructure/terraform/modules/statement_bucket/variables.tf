variable "bucket_name" {
  description = "Must match the Ledger's STATEMENTS_BUCKET_NAME — this is the same bucket the Ledger's S3PresignService issues presigned PUT URLs against (see application.yml's aws.s3.statements-bucket). Owned by Ingest until the Document service takes files over (D8)."
  type        = string
}

variable "cors_allowed_origins" {
  description = "Origins allowed to PUT directly to this bucket via the Ledger's presigned URL (the browser uploads straight to S3, bypassing the Ledger — CLAUDE.md's async statement flow). LocalStack never enforced this; real S3 does, so this is a genuinely new requirement of the AWS-backed setup, not just a port of existing config."
  type        = list(string)
  default     = ["http://localhost:4200"]
}

variable "kms_key_arn" {
  description = "XS-COMP-06 / D13: customer-managed KMS key for the bucket. Null keeps AWS-managed encryption (dev while it holds only the owner's data)."
  type        = string
  default     = null
}

variable "malware_scan_enabled" {
  description = "XS-COMP-07: turns on EventBridge notifications, which GuardDuty Malware Protection needs."
  type        = bool
  default     = false
}

variable "tags" {
  type    = map(string)
  default = {}
}
