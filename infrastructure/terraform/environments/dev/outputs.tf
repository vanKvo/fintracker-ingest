output "api_url" {
  value = aws_apigatewayv2_api.this.api_endpoint
}

output "api_role_arn" {
  description = "Add to the Ledger's INTERNAL_ALLOWED_CALLER_ARNS (invariant 3)."
  value       = module.api_lambda.role_arn
}

output "sweep_role_arn" {
  description = "Add to the Ledger's INTERNAL_ALLOWED_CALLER_ARNS (invariant 3)."
  value       = module.sweep_lambda.role_arn
}

output "statements_bucket" {
  value = module.statement_bucket.bucket_name
}
