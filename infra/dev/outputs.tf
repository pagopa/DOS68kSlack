output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer"
  value       = module.ecs_service.alb_dns_name
}

output "ecs_service_name" {
  description = "Name of the ECS service"
  value       = module.ecs_service.ecs_service_name
}

output "task_definition_arn" {
  description = "ARN of the current task definition"
  value       = module.ecs_service.task_definition_arn
}
