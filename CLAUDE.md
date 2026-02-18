# STVG Helper Bot

Personal Telegram bot hosted on AWS Lambda.

## Tech Stack
- **Bot**: Python 3.12, python-telegram-bot v20+
- **Dependencies**: uv (`pyproject.toml`); runtime deps bundled in Lambda zip, dev deps (boto3, black, isort, mypy) local-only
- **Infrastructure**: Terraform, AWS (Lambda, API Gateway v2, SSM Parameter Store)
- **State**: Terraform S3 backend with DynamoDB locking

## Project Structure
- `bot/` — Lambda function code
- `terraform/` — Infrastructure as code
- `scripts/` — Build and deployment scripts

## Development

### First-time setup
```bash
# 1. Install local dev dependencies
uv sync

# 2. Create S3 bucket + DynamoDB table for Terraform state (once only)
make bootstrap

# 3. Build Lambda zip and deploy infrastructure
make init && make release

# 4. Set the Telegram bot token
aws ssm put-parameter --name "/stvg-helper/telegram-bot-token" \
  --value "YOUR_TOKEN" --type SecureString --overwrite

# 5. Register the webhook with Telegram
make webhook BOT_TOKEN=YOUR_TOKEN
```

### Subsequent deploys
```bash
make release
```

## Conventions
- Python: snake_case, type hints where practical
- Terraform: one resource type per file, descriptive resource names
- All secrets via SSM Parameter Store, never hardcoded
- Dependencies: add runtime deps to `[project.dependencies]`, dev-only deps to `[dependency-groups] dev` in `pyproject.toml`; commit `uv.lock`
- Linting: run `make lint` before committing; use `make black-fix` / `make isort-fix` to auto-fix formatting