# Defense-in-depth layers 2 and 3 — they work even if Sentinel itself is down.
#   Layer 2: AWS Budgets *Action* attaches a Deny-all policy to the sandbox role at 100% of budget.
#   Layer 3: stateless tag-based reaper Lambda (lambda/reaper.py) every 5 minutes.
# Review with `terraform plan` in a throwaway account before production use.

terraform {
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.4" }
  }
}

data "aws_iam_role" "sandbox" { name = var.sandbox_role_name }

# ---------- Layer 2: cloud-native budget kill-switch ----------
resource "aws_iam_policy" "deny_all" {
  name   = "sentinel-budget-deny-all"
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Deny", Action = "*", Resource = "*" }] })
}

resource "aws_iam_role" "budget_action" {
  name = "sentinel-budget-action"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "budgets.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}

resource "aws_iam_role_policy" "budget_action" {
  role = aws_iam_role.budget_action.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Action = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"], Resource = data.aws_iam_role.sandbox.arn }] })
}

resource "aws_budgets_budget" "sandbox" {
  name         = "sentinel-sandbox-monthly"
  budget_type  = "COST"
  limit_amount = var.monthly_limit_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:sentinel:sandbox$"] # any resource carrying the sandbox tag
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
}

resource "aws_budgets_budget_action" "freeze" {
  budget_name        = aws_budgets_budget.sandbox.name
  action_type        = "APPLY_IAM_POLICY"
  approval_model     = "AUTOMATIC"
  notification_type  = "ACTUAL"
  execution_role_arn = aws_iam_role.budget_action.arn

  action_threshold {
    action_threshold_type  = "PERCENTAGE"
    action_threshold_value = 100
  }
  definition {
    iam_action_definition {
      policy_arn = aws_iam_policy.deny_all.arn
      roles      = [var.sandbox_role_name]
    }
  }
  subscriber {
    subscription_type = "EMAIL"
    address           = var.alert_email
  }
}

# ---------- Layer 3: stateless reaper ----------
data "archive_file" "reaper" {
  type        = "zip"
  source_file = "${path.module}/../../lambda/reaper.py"
  output_path = "${path.module}/reaper.zip"
}

resource "aws_iam_role" "reaper" {
  name = "sentinel-reaper"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}

resource "aws_iam_role_policy" "reaper" {
  role = aws_iam_role.reaper.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ec2:DescribeInstances", "ec2:TerminateInstances"], Resource = "*" },
    { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], Resource = "*" }] })
}

resource "aws_lambda_function" "reaper" {
  function_name    = "sentinel-reaper"
  role             = aws_iam_role.reaper.arn
  handler          = "reaper.lambda_entry"
  runtime          = "python3.12"
  filename         = data.archive_file.reaper.output_path
  source_code_hash = data.archive_file.reaper.output_base64sha256
  timeout          = 60
  environment {
    variables = { DRY_RUN = tostring(var.reaper_dry_run) }
  }
}

resource "aws_cloudwatch_event_rule" "every_5_min" {
  name                = "sentinel-reaper-schedule"
  schedule_expression = "rate(5 minutes)"
}
resource "aws_cloudwatch_event_target" "reaper" {
  rule = aws_cloudwatch_event_rule.every_5_min.name
  arn  = aws_lambda_function.reaper.arn
}
resource "aws_lambda_permission" "events" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.reaper.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.every_5_min.arn
}
