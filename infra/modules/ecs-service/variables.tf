variable "app_name" {
  description = "Application name used as prefix for resource names"
  type        = string
}

variable "environment" {
  description = "Environment name (e.g. dev, staging, prod)"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

# ── Networking ────────────────────────────────────────────────────────────────

variable "vpc_id" {
  description = "ID of the VPC"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for ECS tasks"
  type        = list(string)
}

variable "public_subnet_ids" {
  description = "List of public subnet IDs for the ALB (at least two for AZ redundancy)"
  type        = list(string)
}

# ── ECS ───────────────────────────────────────────────────────────────────────

variable "ecs_cluster_arn" {
  description = "ARN of the existing ECS cluster"
  type        = string
}

variable "container_image" {
  description = "Full Docker image URI (e.g. ghcr.io/pagopa/dos68kslack:sha-abc1234)"
  type        = string
}

variable "container_port" {
  description = "Port exposed by the container"
  type        = number
  default     = 8000
}

variable "task_cpu" {
  description = "CPU units for the Fargate task (256 = 0.25 vCPU)"
  type        = number
  default     = 256
}

variable "task_memory" {
  description = "Memory (MiB) for the Fargate task"
  type        = number
  default     = 512
}

variable "desired_count" {
  description = "Number of tasks to run"
  type        = number
  default     = 1
}

# ── Application environment ──────────────────────────────────────────────────

variable "log_level" {
  description = "Python log level"
  type        = string
  default     = "INFO"
}

variable "log_health_checks" {
  description = "Whether to log /health requests"
  type        = bool
  default     = false
}

# ── ALB ───────────────────────────────────────────────────────────────────────

variable "route53_zone_id" {
  description = "ID of the Route 53 hosted zone for DNS records and ACM validation"
  type        = string
}

variable "domain_name" {
  description = "Domain name for the ALB (e.g. dos68k-slack.example.com)"
  type        = string
}

variable "health_check_path" {
  description = "Path used by the ALB health check"
  type        = string
  default     = "/health"
}
