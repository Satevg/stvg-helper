# stvg-helper

Personal Telegram bot hosted on AWS Lambda.

## First-time setup

```bash
# 0. Install local dev dependencies (requires uv)
uv sync

# 1. Create S3 + DynamoDB for Terraform state (once only)
make bootstrap

# 2. Initialise Terraform (once only)
make init

# 3. Build Lambda zip and deploy AWS infrastructure
make release

# 4. Set bot token (get it from @BotFather on Telegram)
aws ssm put-parameter \
  --name "/stvg-helper/telegram-bot-token" \
  --value "YOUR_BOT_TOKEN" \
  --type SecureString \
  --overwrite \
  --region eu-central-1

# 5. Set Anthropic API key (get it from console.anthropic.com → API Keys)
aws ssm put-parameter \
  --name "/stvg-helper/anthropic-api-key" \
  --value "YOUR_ANTHROPIC_API_KEY" \
  --type SecureString \
  --overwrite \
  --region eu-central-1

# 6. Register Telegram webhook
make webhook BOT_TOKEN=YOUR_BOT_TOKEN
```

## Common commands

| Command | Description |
|---|---|
| `make release` | Build zip and deploy (most common) |
| `make package` | Build Lambda zip only |
| `make deploy` | Apply Terraform changes only |
| `make bootstrap` | Create Terraform state backend (once only) |
| `make init` | Initialise Terraform (once only) |
| `make webhook BOT_TOKEN=<token>` | Register the Telegram webhook |
| `make lint` | Run all checks (black, isort, mypy) |
| `make black` | Check formatting |
| `make black-fix` | Reformat code |
| `make isort` | Check import order |
| `make isort-fix` | Reorder imports |
| `make mypy` | Type-check |
