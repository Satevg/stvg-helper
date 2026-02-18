# stvg-helper

Personal Telegram bot hosted on AWS Lambda.

## First-time setup

```bash
# 1. Create S3 + DynamoDB for Terraform state (once only)
bash scripts/bootstrap.sh

# 2. Build Lambda zip
bash scripts/package.sh

# 3. Deploy AWS infrastructure
cd terraform && terraform init && terraform apply

# 4. Set bot token (get it from @BotFather on Telegram)
aws ssm put-parameter \
  --name "/stvg-helper/telegram-bot-token" \
  --value "YOUR_BOT_TOKEN" \
  --type SecureString \
  --overwrite \
  --region eu-central-1

# 5. Register Telegram webhook
curl "https://api.telegram.org/botYOUR_BOT_TOKEN/setWebhook?url=$(terraform -chdir=terraform output -raw webhook_url)"
```

## Deploying code changes

```bash
bash scripts/package.sh && terraform -chdir=terraform apply
```

## Deploying infrastructure changes only

```bash
terraform -chdir=terraform apply
```
