variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "profile" {
  description = "dev | prod (D12). Every environment difference is a key in local.settings."
  type        = string
  validation {
    condition     = contains(["dev", "prod"], var.profile)
    error_message = "profile must be dev or prod."
  }
}

variable "lambda_package_dir" {
  description = "Directory built by scripts/build_lambda_package.sh: the service code plus its dependencies."
  type        = string
  default     = "../../../../build/package"
}

variable "statements_bucket_name" {
  description = "Must match the Ledger's STATEMENTS_BUCKET_NAME: the Ledger issues the presigned upload URLs for this bucket."
  type        = string
}

variable "imports_table_name" {
  type    = string
  default = "FinTracker_Imports"
}

variable "profiles_table_name" {
  type    = string
  default = "FinTracker_FormatProfiles"
}

variable "identity_authorizer_function_arn" {
  description = "User profile service's identity authorizer (D3)."
  type        = string
}

variable "ledger_internal_api_url" {
  description = "Base URL of the Ledger's internal HTTP API (INTERNAL_BASE_URL_LEDGER)."
  type        = string
}

variable "ledger_internal_api_execution_arn" {
  description = "Execution ARN of the Ledger's internal HTTP API, for execute-api:Invoke (D7, D18)."
  type        = string
}

variable "cors_allowed_origins" {
  description = "Origins allowed to PUT to the bucket with the Ledger's presigned URL, and to call this API."
  type        = list(string)
}

variable "malware_scan" {
  description = "IN-IMP-03 / XS-COMP-07: GuardDuty scans uploads and Ingest reads only clean files. Off in phase 1 (only the owner uploads); must be true before anyone else uploads."
  type        = bool
  default     = false
}

variable "expiry_sweep_enabled" {
  description = "IN-IMP-08: the 15-minute cleanup job's schedule is ENABLED or DISABLED. Its first run after being switched on ends every overdue import."
  type        = bool
  default     = true
}

variable "user_events_bus_name" {
  description = "EventBridge bus carrying UserAccountDeleted (XS-DEL). Empty: the deletion handler isn't subscribed yet."
  type        = string
  default     = ""
}

variable "alarm_email" {
  description = "Receives the service's alarms and promotion notices. Empty: subscribe by hand."
  type        = string
  default     = ""
}

variable "promotion_min_users" {
  type    = number
  default = 3
}

variable "promotion_min_agreement" {
  type    = number
  default = 0.8
}

variable "promotion_window_days" {
  type    = number
  default = 30
}
