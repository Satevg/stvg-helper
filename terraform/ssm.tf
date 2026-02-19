resource "aws_ssm_parameter" "bot_token" {
  name        = "/stvg-helper/telegram-bot-token"
  description = "Telegram bot API token"
  type        = "SecureString"
  value       = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "anthropic_api_key" {
  name        = "/stvg-helper/anthropic-api-key"
  description = "Anthropic API key"
  type        = "SecureString"
  value       = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "watcher_username" {
  name        = "/stvg-helper/watcher-username"
  description = "Flussonic Watcher username"
  type        = "SecureString"
  value       = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "watcher_password" {
  name        = "/stvg-helper/watcher-password"
  description = "Flussonic Watcher password"
  type        = "SecureString"
  value       = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [value]
  }
}
