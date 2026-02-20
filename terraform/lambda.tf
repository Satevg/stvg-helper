resource "aws_lambda_function" "bot" {
  function_name = local.function_name
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.bot.repository_url}:latest"
  timeout       = 60
  memory_size   = 512

  environment {
    variables = {
      SSM_BOT_TOKEN_PARAM         = aws_ssm_parameter.bot_token.name
      SSM_ANTHROPIC_API_KEY_PARAM = aws_ssm_parameter.anthropic_api_key.name
      SSM_WATCHER_USERNAME_PARAM  = aws_ssm_parameter.watcher_username.name
      SSM_WATCHER_PASSWORD_PARAM  = aws_ssm_parameter.watcher_password.name
      WATCHER_URL                 = "https://video.unet.by"
      POWERTOOLS_SERVICE_NAME     = "stvg-helper"
    }
  }

  depends_on = [
    aws_iam_role_policy.lambda,
    aws_cloudwatch_log_group.lambda,
  ]
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = 14
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.bot.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.bot.execution_arn}/*/*"
}
