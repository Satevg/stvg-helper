# Deploy the Bot

## Regular deploy (code changes)
```bash
make release
```
This packages the Lambda zip and applies Terraform in one step.

## Infrastructure-only changes (no code changes)
```bash
make deploy
```

## First-time setup (once only)
```bash
uv sync
make bootstrap   # creates S3 + DynamoDB for Terraform state
make init        # initialises Terraform
make release     # first deploy

# Set the bot token
aws ssm put-parameter --name "/stvg-helper/telegram-bot-token" \
  --value "YOUR_TOKEN" --type SecureString --overwrite --region eu-central-1

# Register the webhook
make webhook BOT_TOKEN=YOUR_TOKEN
```

## Re-register the webhook (if the API Gateway URL ever changes)
```bash
make webhook BOT_TOKEN=YOUR_TOKEN
```

## Verify the deploy worked
Check CloudWatch Logs for the Lambda function after sending a message to the bot.