# IAM user for Grafana Cloud to read CloudWatch metrics and logs

resource "aws_iam_user" "grafana" {
  name = "grafana-cloudwatch-reader"
}

data "aws_iam_policy_document" "grafana_readonly" {
  statement {
    sid = "CloudWatchReadOnly"
    actions = [
      "cloudwatch:DescribeAlarmsForMetric",
      "cloudwatch:DescribeAlarmHistory",
      "cloudwatch:DescribeAlarms",
      "cloudwatch:ListMetrics",
      "cloudwatch:GetMetricData",
      "cloudwatch:GetInsightRuleReport",
    ]
    resources = ["*"]
  }

  statement {
    sid = "CloudWatchLogsReadOnly"
    actions = [
      "logs:DescribeLogGroups",
      "logs:GetLogGroupFields",
      "logs:StartQuery",
      "logs:StopQuery",
      "logs:GetQueryResults",
      "logs:GetLogEvents",
      "logs:FilterLogEvents",
    ]
    resources = ["*"]
  }

  statement {
    sid = "EC2DescribeRegions"
    actions = [
      "ec2:DescribeRegions",
    ]
    resources = ["*"]
  }

  statement {
    sid = "TagReadOnly"
    actions = [
      "tag:GetResources",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_user_policy" "grafana" {
  name   = "grafana-cloudwatch-readonly"
  user   = aws_iam_user.grafana.name
  policy = data.aws_iam_policy_document.grafana_readonly.json
}

resource "aws_iam_access_key" "grafana" {
  user = aws_iam_user.grafana.name
}

resource "aws_ssm_parameter" "grafana_access_key_id" {
  name  = "/stvg-helper/grafana-access-key-id"
  type  = "SecureString"
  value = aws_iam_access_key.grafana.id
}

resource "aws_ssm_parameter" "grafana_secret_access_key" {
  name  = "/stvg-helper/grafana-secret-access-key"
  type  = "SecureString"
  value = aws_iam_access_key.grafana.secret
}
