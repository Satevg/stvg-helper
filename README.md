# stvg-helper

Personal Telegram bot hosted on AWS Lambda.

## Features

- **Menu** — persistent reply keyboard with quick-action buttons
- **Parking** — finds a free parking spot by analysing live camera snapshots with local YOLOv8n vehicle detection (Flussonic Watcher integration)
- **Claude chat** — free-form messages forwarded to `claude-haiku-4-5-20251001`
- **Warm Lambda** — EventBridge pings the function every 5 minutes to avoid cold starts

## First-time setup

```bash
# 0. Install local dev dependencies (requires uv)
uv sync

# 1. Export YOLOv8n ONNX model (once only, requires ultralytics)
pip install ultralytics
yolo export model=yolov8n.pt format=onnx imgsz=640
mkdir -p models && mv yolov8n.onnx models/

# 2. Create S3 + DynamoDB for Terraform state (once only)
make bootstrap

# 3. Initialise Terraform (once only)
make init

# 4. Create ECR repository first, then build and push the container image
terraform -chdir=terraform apply -target=aws_ecr_repository.bot
make package

# 5. Deploy remaining AWS infrastructure
terraform -chdir=terraform apply

# 6. Set bot token (get it from @BotFather on Telegram)
aws ssm put-parameter \
  --name "/stvg-helper/telegram-bot-token" \
  --value "YOUR_BOT_TOKEN" \
  --type SecureString \
  --overwrite \
  --region eu-central-1

# 7. Set Anthropic API key (get it from console.anthropic.com → API Keys)
aws ssm put-parameter \
  --name "/stvg-helper/anthropic-api-key" \
  --value "YOUR_ANTHROPIC_API_KEY" \
  --type SecureString \
  --overwrite \
  --region eu-central-1

# 8. Set Flussonic Watcher credentials (video.unet.by)
aws ssm put-parameter \
  --name "/stvg-helper/watcher-username" \
  --value "YOUR_WATCHER_USERNAME" \
  --type SecureString \
  --overwrite \
  --region eu-central-1
aws ssm put-parameter \
  --name "/stvg-helper/watcher-password" \
  --value "YOUR_WATCHER_PASSWORD" \
  --type SecureString \
  --overwrite \
  --region eu-central-1

# 9. Register Telegram webhook
make webhook BOT_TOKEN=YOUR_BOT_TOKEN
```

## Common commands

| Command | Description |
|---|---|
| `make release` | Build and push container image, then deploy (most common) |
| `make package` | Build and push Docker image to ECR only |
| `make deploy` | Apply Terraform changes and update Lambda image |
| `make bootstrap` | Create Terraform state backend (once only) |
| `make init` | Initialise Terraform (once only) |
| `make webhook BOT_TOKEN=<token>` | Register the Telegram webhook |
| `make lint` | Run all checks (black, isort, mypy) |
| `make test` | Run unit tests |
| `make black` | Check formatting |
| `make black-fix` | Reformat code |
| `make isort` | Check import order |
| `make isort-fix` | Reorder imports |
| `make mypy` | Type-check |

## Tuning parking detection

```bash
# Print coverage ratios for all cameras against live snapshots
YOLO_MODEL_PATH=models/yolov8n.onnx uv run scripts/calibrate.py
```

Adjust `COVERAGE_THRESHOLD` in `bot/parking.py` based on the output (default: `0.40`).
