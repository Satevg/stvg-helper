output "api_gateway_url" {
  description = "API Gateway endpoint URL"
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "webhook_url" {
  description = "Full webhook URL to register with Telegram"
  value       = "${trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")}/webhook"
}

output "lambda_function_name" {
  description = "Lambda function name"
  value       = aws_lambda_function.bot.function_name
}

output "ecr_image_uri" {
  description = "ECR image URI (latest tag) for the bot container"
  value       = "${aws_ecr_repository.bot.repository_url}:latest"
}

output "ecr_repository_url" {
  description = "ECR repository URL"
  value       = aws_ecr_repository.bot.repository_url
}
