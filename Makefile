.PHONY: bootstrap init package deploy release webhook black black-fix isort isort-fix mypy lint test

## One-time: create S3 + DynamoDB for Terraform state
bootstrap:
	@read -p "This will create AWS resources (S3 bucket + DynamoDB table). Continue? [y/N] " ans && [ "$$ans" = "y" ] || (echo "Aborted."; exit 1)
	bash scripts/bootstrap.sh

## One-time: initialise Terraform
init:
	terraform -chdir=terraform init

## Build Docker image and push to ECR
package:
	bash scripts/deploy.sh

## Apply infrastructure changes and update Lambda to the latest image
deploy:
	terraform -chdir=terraform apply
	aws lambda update-function-code \
		--function-name $$(terraform -chdir=terraform output -raw lambda_function_name) \
		--image-uri $$(terraform -chdir=terraform output -raw ecr_image_uri)

## Build image, push to ECR, and deploy (most common workflow)
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
