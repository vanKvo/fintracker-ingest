terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # Local backend while one developer deploys dev (same as the legacy Data pipeline stack).
  backend "local" {
    path = "terraform.tfstate"
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.profile # ADR-008: one AWS account per environment, reached through the CLI profile of the same name

  default_tags {
    tags = local.common_tags
  }
}
