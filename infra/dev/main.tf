terraform {
  required_version = ">= 1.15"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket = "terraform-backend-20230531161049141900000001"
    key    = "dos68k/tfstate"
    region = "eu-south-1"
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "dos68k-slack"
      Environment = var.environment
      CreatedBy   = "terraform"
      Owner       = "DOS68kSlack"
      Source      = "https://github.com/pagopa/DOS68kSlack"
      CostCenter  = "PNRR 1.4.3 Cloud Gaap"
    }
  }
}

# ── Data Sources ──────────────────────────────────────────────────────────────

data "aws_ecs_cluster" "main" {
  cluster_name = var.ecs_cluster_name
}

data "aws_subnets" "private" {
  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }

  filter {
    name   = "tag:Name"
    values = ["*private*", "*Private*"]
  }
}

data "aws_subnets" "public" {
  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }

  filter {
    name   = "tag:Name"
    values = ["*public*", "*Public*"]
  }
}

locals {
  route53_zone_name = var.route53_zone_name != "" ? var.route53_zone_name : "${var.environment}.developer.pagopa.it"
}

data "aws_route53_zone" "main" {
  name         = local.route53_zone_name
  private_zone = false
}

# ── ECS Service Module ────────────────────────────────────────────────────────

module "ecs_service" {
  source = "../modules/ecs-service"

  app_name    = var.app_name
  environment = var.environment
  aws_region  = var.aws_region

  # Networking
  vpc_id             = var.vpc_id
  private_subnet_ids = data.aws_subnets.private.ids
  public_subnet_ids  = data.aws_subnets.public.ids

  # ECS
  ecs_cluster_arn             = data.aws_ecs_cluster.main.arn
  container_image             = var.container_image
  task_cpu                    = var.task_cpu
  task_memory                 = var.task_memory

  # Application environment
  log_level         = var.log_level
  log_health_checks = var.log_health_checks

  # DNS & TLS
  route53_zone_id = data.aws_route53_zone.main.zone_id
  domain_name     = var.domain_name
}
