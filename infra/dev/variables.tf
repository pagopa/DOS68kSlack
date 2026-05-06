variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "eu-south-1"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "dev"
}

variable "app_name" {
  description = "Application name"
  type        = string
  default     = "dos68k-slack"
}

variable "ecs_cluster_name" {
  description = "Name of the existing ECS cluster"
  type        = string
  default     = "dos68k-dev-ecs-cluster"
}

variable "container_image" {
  description = "Full Docker image reference to deploy (e.g. ghcr.io/pagopa/dos68kslack:sha-abc1234)"
  type        = string
  default     = "ghcr.io/pagopa/dos68kslack:sha-b09ad91"
}

variable "vpc_id" {
  description = "ID of the VPC where resources are deployed"
  type        = string
  default     = "vpc-0f76e62d7ee2e2923"
}

variable "log_level" {
  description = "Application log level"
  type        = string
  default     = "INFO"
}

variable "log_health_checks" {
  description = "Whether to log /health endpoint requests"
  type        = bool
  default     = false
}

variable "task_cpu" {
  description = "CPU units for the ECS task (256 = 0.25 vCPU)"
  type        = number
  default     = 256
}

variable "task_memory" {
  description = "Memory (MiB) for the ECS task"
  type        = number
  default     = 512
}

variable "route53_zone_name" {
  description = "Route 53 hosted zone name (derived from environment: <env>.developer.pagopa.it)"
  type        = string
  default     = "dev.developer.pagopa.it"
}

variable "domain_name" {
  description = "Domain name for the ALB (e.g. dos68k-slack.example.com)"
  type        = string
  default     = "dos68kslack.dev.developer.pagopa.it"
}
