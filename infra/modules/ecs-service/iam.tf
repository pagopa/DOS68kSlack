data "aws_caller_identity" "current" {}

# ── Task Execution Role ──────────────────────────────────────────────────────
# Used by the ECS agent to pull the image, write logs, and read secrets.

resource "aws_iam_role" "task_execution" {
  name = "${var.app_name}-${var.environment}-task-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "task_execution_secrets" {
  name = "${var.app_name}-${var.environment}-secrets-read"
  role = aws_iam_role.task_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadSSMParameters"
        Effect = "Allow"
        Action = ["ssm:GetParameters", "ssm:GetParameter"]
        Resource = [
          aws_ssm_parameter.slack_bot_token.arn,
          aws_ssm_parameter.slack_signing_secret.arn,
          aws_ssm_parameter.chatbot_api_key.arn,
          aws_ssm_parameter.chatbot_base_url.arn,
        ]
      },
      {
        Sid    = "DecryptSSMWithDefaultKey"
        Effect = "Allow"
        Action = ["kms:Decrypt"]
        Resource = [
          "arn:aws:kms:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"
        ]
      }
    ]
  })
}

# ── Task Role ─────────────────────────────────────────────────────────────────
# Assumed by the running container. Add DynamoDB / other policies here.

resource "aws_iam_role" "task" {
  name = "${var.app_name}-${var.environment}-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}
