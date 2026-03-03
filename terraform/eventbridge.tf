resource "aws_cloudwatch_event_rule" "warmup" {
  name                = "${local.function_name}-warmup"
  description         = "Keeps the Lambda warm by pinging every 5 minutes"
  schedule_expression = "rate(3 minutes)"
}

resource "aws_cloudwatch_event_target" "warmup" {
  rule      = aws_cloudwatch_event_rule.warmup.name
  target_id = "lambda"
  arn       = aws_lambda_function.bot.arn
}

resource "aws_lambda_permission" "eventbridge_warmup" {
  statement_id  = "AllowEventBridgeWarmupInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.bot.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.warmup.arn
}
