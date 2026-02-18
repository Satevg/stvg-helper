# STVG Helper Bot

Personal Telegram bot hosted on AWS Lambda.

## Tech Stack
- **Bot**: Python 3.12, python-telegram-bot v20+
- **Infrastructure**: Terraform, AWS (Lambda, API Gateway v2, SSM Parameter Store)
- **State**: Terraform S3 backend with DynamoDB locking

## Project Structure
- `bot/` — Lambda function code
- `terraform/` — Infrastructure as code
- `scripts/` — Build and deployment scripts

## Development

### First-time setup
```bash
# 1. Create S3 bucket + DynamoDB table for Terraform state (once only)
bash scripts/bootstrap.sh

# 2. Build Lambda deployment package
bash scripts/package.sh

# 3. Deploy infrastructure
cd terraform && terraform init && terraform apply

# 4. Set the Telegram bot token
aws ssm put-parameter --name "/stvg-helper/telegram-bot-token" \
  --value "YOUR_TOKEN" --type SecureString --overwrite

# 5. Register the webhook with Telegram (use webhook_url from terraform output)
curl "https://api.telegram.org/botYOUR_TOKEN/setWebhook?url=$(terraform -chdir=terraform output -raw webhook_url)"
```

### Subsequent deploys
```bash
bash scripts/package.sh && terraform -chdir=terraform apply
```

## Conventions
- Python: snake_case, type hints where practical
- Terraform: one resource type per file, descriptive resource names
- All secrets via SSM Parameter Store, never hardcoded