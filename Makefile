.PHONY: bootstrap init package deploy release webhook black black-fix isort isort-fix mypy lint test

## One-time: create S3 + DynamoDB for Terraform state
bootstrap:
	@read -p "This will create AWS resources (S3 bucket + DynamoDB table). Continue? [y/N] " ans && [ "$$ans" = "y" ] || (echo "Aborted."; exit 1)
	bash scripts/bootstrap.sh

## One-time: initialise Terraform
init:
	terraform -chdir=terraform init

## Build Lambda deployment zip
package:
	bash scripts/package.sh

## Apply infrastructure changes only
deploy:
	terraform -chdir=terraform apply

## Build zip and deploy (most common workflow)
release: package deploy

## Check formatting with black (fails if any file would be changed)
black:
	uv run black --check bot/

## Reformat code with black
black-fix:
	uv run black bot/

## Check import order with isort (fails if any file would be changed)
isort:
	uv run isort --check bot/

## Reorder imports with isort
isort-fix:
	uv run isort bot/

## Type-check with mypy
mypy:
	uv run mypy bot/

## Run unit tests
test:
	uv run pytest tests/

## Run all checks (black, isort, mypy)
lint: black isort mypy

## Register the Telegram webhook (requires BOT_TOKEN env var)
webhook:
	@test -n "$(BOT_TOKEN)" || (echo "Usage: make webhook BOT_TOKEN=<token>"; exit 1)
	curl "https://api.telegram.org/bot$(BOT_TOKEN)/setWebhook?url=$$(terraform -chdir=terraform output -raw webhook_url)"
