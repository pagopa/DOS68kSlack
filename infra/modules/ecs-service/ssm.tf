# SSM parameters injected into the ECS task via the `secrets` block.
# Values are created with a placeholder; update them manually before deploying:
#   aws ssm put-parameter --name "..." --value "real-value" --type SecureString --overwrite
#   aws ssm put-parameter --name "..." --value "real-value" --type String --overwrite

resource "aws_ssm_parameter" "slack_bot_token" {
  name        = "/${var.app_name}/slack_bot_token"
  description = "Slack bot OAuth token (xoxb-...)"
  type        = "SecureString"
  value       = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "slack_signing_secret" {
  name        = "/${var.app_name}/slack_signing_secret"
  description = "Slack app signing secret"
  type        = "SecureString"
  value       = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "chatbot_api_key" {
  name        = "/${var.app_name}/chatbot_api_key"
  description = "DOS68K chatbot API key"
  type        = "SecureString"
  value       = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "chatbot_base_url" {
  name        = "/${var.app_name}/chatbot_base_url"
  description = "Base URL of the DOS68K chatbot API"
  type        = "String"
  value       = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [value]
  }
}
