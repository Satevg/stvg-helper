resource "aws_lambda_function" "bot" {
  function_name = local.function_name
  role          = aws_iam_role.lambda.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 30
  memory_size   = 128

  filename         = local.lambda_zip_path
  source_code_hash = local.lambda_zip_exists ? filebase64sha256(local.lambda_zip_path) : null

  environment {
    variables = {
      SSM_BOT_TOKEN_PARAM = aws_ssm_parameter.bot_token.name
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
