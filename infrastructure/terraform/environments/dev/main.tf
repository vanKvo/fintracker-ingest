# Ingest service (IN-IMP, IN-FMT, IN-RDR): one FastAPI Lambda behind the HTTP API's identity authorizer,
# the 15-minute cleanup Lambda, two DynamoDB tables, the statement bucket and its optional malware scan.

data "aws_caller_identity" "current" {}

locals {
  name = "FinTracker-Ingest-${var.profile}"

  common_tags = {
    Project     = "fintracker"
    Service     = "ingest"
    Environment = var.profile
    ManagedBy   = "terraform"
  }

  # Architecture doc 6.1: every environment difference is a key here and a row in the 6.1 table.
  settings = {
    dev  = { cmk = false, dynamodb_pitr = false, log_retention_days = 7, api_throttle_rate_limit = 10, api_throttle_burst_limit = 20 }
    prod = { cmk = true, dynamodb_pitr = true, log_retention_days = 90, api_throttle_rate_limit = 100, api_throttle_burst_limit = 200 }
  }[var.profile]

  kms_key_arn = local.settings.cmk ? aws_kms_key.ingest[0].arn : null

  shared_env = {
    APP_ENV                  = var.profile
    IMPORTS_TABLE            = aws_dynamodb_table.imports.name
    PROFILES_TABLE           = aws_dynamodb_table.profiles.name
    STATEMENT_BUCKET         = module.statement_bucket.bucket_name
    INTERNAL_BASE_URL_LEDGER = var.ledger_internal_api_url
    MALWARE_SCAN_REQUIRED    = tostring(var.malware_scan)
    PROMOTION_MIN_USERS      = tostring(var.promotion_min_users)
    PROMOTION_MIN_AGREEMENT  = tostring(var.promotion_min_agreement)
    PROMOTION_WINDOW_DAYS    = tostring(var.promotion_window_days)
    PROMOTION_TOPIC_ARN      = aws_sns_topic.ingest.arn
    POWERTOOLS_SERVICE_NAME  = "ingest-service"
  }

  # IN-IMP-10: only what each function needs. No wildcard actions or resources.
  tables_statement = {
    sid     = "ImportAndProfileTables"
    actions = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:BatchWriteItem"]
    resources = [
      aws_dynamodb_table.imports.arn, "${aws_dynamodb_table.imports.arn}/index/status-updatedAt",
      aws_dynamodb_table.profiles.arn, "${aws_dynamodb_table.profiles.arn}/index/user-votes",
    ]
  }
  ledger_statement = {
    sid       = "CallLedgerInternalApi"
    actions   = ["execute-api:Invoke"]
    resources = ["${var.ledger_internal_api_execution_arn}/*/*/api/v1/ledger/*"]
  }
  bucket_read_statement = {
    sid       = "ReadUploadedStatements"
    actions   = ["s3:GetObject", "s3:GetObjectTagging"]
    resources = ["${module.statement_bucket.bucket_arn}/statements/*"]
  }
  promotion_statement = {
    sid       = "NotifyOwnerOfPromotions"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.ingest.arn]
  }
}

data "archive_file" "package" {
  type        = "zip"
  source_dir  = var.lambda_package_dir
  output_path = "${path.module}/build/ingest_package.zip"
}

# --- XS-COMP-06: keys (D13) --------------------------------------------------------------------

resource "aws_kms_key" "ingest" {
  count                   = local.settings.cmk ? 1 : 0
  description             = "${local.name}: statement bucket and DynamoDB tables (D13)"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_iam_role_policy" "use_key" {
  for_each = local.settings.cmk ? {
    api      = module.api_lambda.role_name
    sweep    = module.sweep_lambda.role_name
    deletion = module.deletion_lambda.role_name
  } : {}

  name = "UseIngestKey"
  role = each.value
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"], Resource = [aws_kms_key.ingest[0].arn] }]
  })
}

# --- Storage --------------------------------------------------------------------------------------

module "statement_bucket" {
  source               = "../../modules/statement_bucket"
  bucket_name          = var.statements_bucket_name
  cors_allowed_origins = var.cors_allowed_origins
  kms_key_arn          = local.kms_key_arn
  malware_scan_enabled = var.malware_scan
  tags                 = local.common_tags
}

# IN-IMP Appendix B: one record per import; the status-updatedAt index serves the cleanup job.
resource "aws_dynamodb_table" "imports" {
  name         = var.imports_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "importId"

  attribute {
    name = "importId"
    type = "S"
  }
  attribute {
    name = "status"
    type = "S"
  }
  attribute {
    name = "updatedAt"
    type = "S"
  }

  global_secondary_index {
    name            = "status-updatedAt"
    hash_key        = "status"
    range_key       = "updatedAt"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = local.settings.dynamodb_pitr
  }

  server_side_encryption {
    enabled     = local.kms_key_arn != null
    kms_key_arn = local.kms_key_arn
  }
}

# IN-FMT Appendix F: shared defaults, users' own profiles, votes, notices and daily counters.
resource "aws_dynamodb_table" "profiles" {
  name         = var.profiles_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }
  attribute {
    name = "SK"
    type = "S"
  }
  attribute {
    name = "voterUserId"
    type = "S"
  }

  global_secondary_index {
    name            = "user-votes"
    hash_key        = "voterUserId"
    projection_type = "KEYS_ONLY"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = local.settings.dynamodb_pitr
  }

  server_side_encryption {
    enabled     = local.kms_key_arn != null
    kms_key_arn = local.kms_key_arn
  }
}

# --- Functions ----------------------------------------------------------------------------------

module "api_lambda" {
  source                   = "../../modules/lambda_function"
  function_name            = "${local.name}-api"
  handler                  = "src.main.handler"
  memory_size              = 1024 # a 5,000-row file is read, typed and checked within API Gateway's 29 s
  timeout                  = 28
  package_filename         = data.archive_file.package.output_path
  package_source_code_hash = data.archive_file.package.output_base64sha256
  environment_variables    = local.shared_env
  extra_policy_statements  = [local.tables_statement, local.ledger_statement, local.bucket_read_statement, local.promotion_statement]
  log_retention_days       = local.settings.log_retention_days
  tags                     = local.common_tags
}

module "sweep_lambda" {
  source                   = "../../modules/lambda_function"
  function_name            = "${local.name}-sweep"
  handler                  = "src.sweep.handler.handler"
  timeout                  = 120
  package_filename         = data.archive_file.package.output_path
  package_source_code_hash = data.archive_file.package.output_base64sha256
  environment_variables    = local.shared_env
  extra_policy_statements  = [local.tables_statement, local.ledger_statement]
  log_retention_days       = local.settings.log_retention_days
  tags                     = local.common_tags
}

module "deletion_lambda" {
  source                   = "../../modules/lambda_function"
  function_name            = "${local.name}-user-account-deleted"
  handler                  = "src.profiles.deletion_handler.handler"
  package_filename         = data.archive_file.package.output_path
  package_source_code_hash = data.archive_file.package.output_base64sha256
  environment_variables    = local.shared_env
  extra_policy_statements  = [local.tables_statement]
  log_retention_days       = local.settings.log_retention_days
  tags                     = local.common_tags
}

# --- IN-IMP-08: the cleanup job, with an on/off switch ----------------------------------------

resource "aws_iam_role" "scheduler" {
  name = "${local.name}-scheduler"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "scheduler.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "scheduler_invoke_sweep" {
  name = "InvokeSweep"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = [module.sweep_lambda.function_arn] }]
  })
}

resource "aws_scheduler_schedule" "sweep" {
  name                = "${local.name}-expiry-sweep"
  schedule_expression = "rate(15 minutes)"
  state               = var.expiry_sweep_enabled ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = module.sweep_lambda.function_arn
    role_arn = aws_iam_role.scheduler.arn
  }
}

# --- IN-FMT-09: account deletion -------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "user_account_deleted" {
  count          = var.user_events_bus_name == "" ? 0 : 1
  name           = "${local.name}-user-account-deleted"
  event_bus_name = var.user_events_bus_name
  event_pattern  = jsonencode({ "detail-type" = ["UserAccountDeleted"] })
}

resource "aws_cloudwatch_event_target" "user_account_deleted" {
  count          = var.user_events_bus_name == "" ? 0 : 1
  rule           = aws_cloudwatch_event_rule.user_account_deleted[0].name
  event_bus_name = var.user_events_bus_name
  arn            = module.deletion_lambda.function_arn
}

resource "aws_lambda_permission" "user_account_deleted" {
  count         = var.user_events_bus_name == "" ? 0 : 1
  statement_id  = "AllowUserAccountDeleted"
  action        = "lambda:InvokeFunction"
  function_name = module.deletion_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.user_account_deleted[0].arn
}

# --- IN-IMP-03 / XS-COMP-07: malware scan, behind the switch -----------------------------------

module "malware_protection" {
  count               = var.malware_scan ? 1 : 0
  source              = "../../modules/malware_protection"
  bucket_name         = module.statement_bucket.bucket_name
  bucket_arn          = module.statement_bucket.bucket_arn
  kms_key_arn         = local.kms_key_arn
  alarm_sns_topic_arn = aws_sns_topic.ingest.arn
  tags                = local.common_tags
}

# --- User-facing API (IN-IMP Appendix A) -------------------------------------------------------

resource "aws_apigatewayv2_api" "this" {
  name          = "${local.name}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = var.cors_allowed_origins
    allow_methods = ["GET", "POST"]
    allow_headers = ["authorization", "content-type"]
    max_age       = 3000
  }
}

# Invariant 2: the User profile service's identity authorizer sets the internal user ID.
resource "aws_apigatewayv2_authorizer" "identity" {
  api_id                            = aws_apigatewayv2_api.this.id
  authorizer_type                   = "REQUEST"
  authorizer_uri                    = "arn:aws:apigateway:${var.aws_region}:lambda:path/2015-03-31/functions/${var.identity_authorizer_function_arn}/invocations"
  authorizer_payload_format_version = "2.0"
  enable_simple_responses           = true
  identity_sources                  = ["$request.header.Authorization"]
  authorizer_result_ttl_in_seconds  = 60
  name                              = "UserProfileIdentityAuthorizer"
}

resource "aws_lambda_permission" "identity_authorizer_invoke" {
  statement_id  = "AllowIngestApiAuthorizerInvoke"
  action        = "lambda:InvokeFunction"
  function_name = var.identity_authorizer_function_arn
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/authorizers/${aws_apigatewayv2_authorizer.identity.id}"
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = module.api_lambda.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 29000
}

resource "aws_apigatewayv2_route" "imports" {
  for_each = toset([
    "POST /api/v1/ingest/imports",
    "GET /api/v1/ingest/imports/{importId}",
    "POST /api/v1/ingest/imports/{importId}/preview",
    "POST /api/v1/ingest/imports/{importId}/confirm",
    "POST /api/v1/ingest/imports/{importId}/cancel",
  ])

  api_id             = aws_apigatewayv2_api.this.id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.api.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.identity.id
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = local.settings.api_throttle_rate_limit
    throttling_burst_limit = local.settings.api_throttle_burst_limit
  }
}

resource "aws_lambda_permission" "api_invoke" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.api_lambda.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}

# --- Alarms and notices (IN-IMP-11, IN-FMT-06, IN-FMT-08) -------------------------------------

resource "aws_sns_topic" "ingest" {
  name              = "${local.name}-alarms"
  kms_master_key_id = local.kms_key_arn
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.ingest.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

locals {
  # Log events that page the owner: one metric filter and one alarm each.
  alarm_events = {
    SCAN_TIMEOUT                 = module.sweep_lambda.log_group_name
    SWEEP_FAILED                 = module.sweep_lambda.log_group_name
    LEDGER_FAILURE_NOTICE_FAILED = module.api_lambda.log_group_name
    BANK_FORMAT_CHANGED          = module.api_lambda.log_group_name
  }
}

resource "aws_cloudwatch_log_metric_filter" "events" {
  for_each       = local.alarm_events
  name           = "${local.name}-${each.key}"
  log_group_name = each.value
  pattern        = "{ $.message = \"${each.key}\" }"

  metric_transformation {
    name      = "Ingest${replace(title(lower(replace(each.key, "_", " "))), " ", "")}"
    namespace = "FinTracker"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "events" {
  for_each            = local.alarm_events
  alarm_name          = "${local.name}-${each.key}"
  namespace           = "FinTracker"
  metric_name         = aws_cloudwatch_log_metric_filter.events[each.key].metric_transformation[0].name
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ingest.arn]
}

locals {
  # IN-FMT-06: banks with shared defaults; each gets its own proposal-changed alarm.
  seed_banks = distinct([for p in jsondecode(file("${path.module}/../../../../seed/format_profiles.json")) : p.bankId])
}

# IN-FMT-06: for one bank, more than 30% of confirmations change the proposal over 7 days, with at least 5.
resource "aws_cloudwatch_metric_alarm" "proposal_changed_share" {
  for_each            = toset(local.seed_banks)
  alarm_name          = "${local.name}-proposal-changed-share-${each.key}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0.3
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ingest.arn]

  metric_query {
    id          = "share"
    expression  = "IF(confirmations >= 5, changed / confirmations, 0)"
    return_data = true
  }
  metric_query {
    id = "confirmations"
    metric {
      namespace   = "FinTracker"
      metric_name = "ProposalConfirmations"
      dimensions  = { service = "ingest-service", bank = each.key }
      period      = 604800
      stat        = "Sum"
    }
  }
  metric_query {
    id = "changed"
    metric {
      namespace   = "FinTracker"
      metric_name = "ProposalChanged"
      dimensions  = { service = "ingest-service", bank = each.key }
      period      = 604800
      stat        = "Sum"
    }
  }
}
