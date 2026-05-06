# ── Application Auto Scaling ──────────────────────────────────────────────────

resource "aws_appautoscaling_target" "ecs" {
  max_capacity       = var.desired_count
  min_capacity       = 0
  resource_id        = "service/${split("/", var.ecs_cluster_arn)[1]}/${aws_ecs_service.app.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

# Scale up to 1 task Mon–Fri at 09:00 CET
resource "aws_appautoscaling_scheduled_action" "scale_up" {
  name               = "${var.app_name}-${var.environment}-scale-up"
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  schedule           = "cron(0 8 ? * MON-FRI *)"
  timezone           = "Europe/Rome"

  scalable_target_action {
    min_capacity = var.desired_count
    max_capacity = var.desired_count
  }
}

# Scale down to 0 tasks Mon–Fri at 18:00 CET
resource "aws_appautoscaling_scheduled_action" "scale_down" {
  name               = "${var.app_name}-${var.environment}-scale-down"
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  schedule           = "cron(0 17 ? * MON-FRI *)"
  timezone           = "Europe/Rome"

  scalable_target_action {
    min_capacity = 0
    max_capacity = 0
  }
}

# Keep 0 tasks on Saturday (catch-all for weekend)
resource "aws_appautoscaling_scheduled_action" "weekend_off" {
  name               = "${var.app_name}-${var.environment}-weekend-off"
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  schedule           = "cron(0 0 ? * SAT *)"
  timezone           = "Europe/Rome"

  scalable_target_action {
    min_capacity = 0
    max_capacity = 0
  }
}
