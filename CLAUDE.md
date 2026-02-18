# STVG Helper Bot

Personal Telegram bot hosted on AWS Lambda.

## Tech Stack
- **Bot**: Python 3.12, python-telegram-bot v20+, Anthropic SDK
- **AI**: Free-form messages forwarded to Claude (`claude-haiku-4-5-20251001`)
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

# 5. Set the Anthropic API key (console.anthropic.com → API Keys)
aws ssm put-parameter --name "/stvg-helper/anthropic-api-key" \
  --value "YOUR_ANTHROPIC_API_KEY" --type SecureString --overwrite

# 6. Register the webhook with Telegram
make webhook BOT_TOKEN=YOUR_TOKEN
```

### Subsequent deploys
```bash
make release
```

## Architecture Notes
- **Event loop singleton**: `_loop` and `_application` are module-level singletons intentionally kept alive across warm Lambda invocations. Do not close the event loop or rebuild the application per request — the httpx client inside `Application` is bound to the event loop and breaks if the loop is recreated.
- **`AnyApplication` type alias**: `Application` from python-telegram-bot is generic with 6 type parameters; `AnyApplication = Application[Any, Any, Any, Any, Any, Any]` is used throughout to satisfy mypy strict mode.
- **Message routing**: menu button labels ("Hello", "Bye") are matched first by `menu_button_handler`; all other non-command text falls through to `claude_handler`. Always register specific handlers before the catch-all.
- **Claude API**: uses `AsyncAnthropic` client with `claude-haiku-4-5-20251001`. API key stored in SSM at `/stvg-helper/anthropic-api-key`.

## Conventions
- Python: snake_case, type hints where practical
- Terraform: one resource type per file, descriptive resource names
- All secrets via SSM Parameter Store, never hardcoded
- Dependencies: add runtime deps to `[project.dependencies]`, dev-only deps to `[dependency-groups] dev` in `pyproject.toml`; commit `uv.lock`
- Linting: run `make lint` before committing; use `make black-fix` / `make isort-fix` to auto-fix formatting