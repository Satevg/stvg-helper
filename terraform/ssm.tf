resource "aws_ssm_parameter" "bot_token" {
  name        = "/stvg-helper/telegram-bot-token"
  description = "Telegram bot API token"
  type        = "SecureString"
  value       = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [value]
  }
}
