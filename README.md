# stvg-helper

Personal Telegram bot hosted on AWS Lambda.

## Features

- **Menu** — persistent reply keyboard with quick-action buttons
- **Autonomous Parking** — finds a free parking spot by identifying unoccupied "hotspots" learned over time from live camera snapshots.
- **Claude chat** — free-form messages forwarded to `claude-haiku-4-5-20251001`
- **Background Learning** — EventBridge triggers a background scan every 5 minutes to keep the parking heatmap up to date without manual checks.

## How Parking Works

Unlike systems that require manual zone configuration, this bot **learns** where people park:
1. Every time a camera is scanned (manually or automatically), car positions are recorded in DynamoDB.
2. If a vehicle is seen in the same area multiple times, it is confirmed as a "parking slot."
3. A spot is reported as **FREE** if a confirmed slot is currently unoccupied.
4. The system automatically adapts to changes in parking layout over time.

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

# 5. Deploy remaining AWS infrastructure (Lambda, DynamoDB, IAM)
terraform -chdir=terraform apply

# 6. Set bot token (get it from @BotFather on Telegram)
aws ssm put-parameter \
  --name "/stvg-helper/telegram-bot-token" \
  --value "YOUR_BOT_TOKEN" \
  --type SecureString \
  --overwrite \
  --region eu-central-1

# 7. Set Anthropic API key (get it from console.anthropic.com)
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
| `make lint` | Run all checks (black, isort, mypy) |
| `make test` | Run unit tests |

## Cost & Limits (AWS Free Tier)

This bot is designed to stay **free forever**:
- **Lambda:** ~8,600 warmup/learning requests + manual usage (Free tier: 1M)
- **DynamoDB:** Stores parking hotspots and usage stats (Free tier: 25 RCU/WCU)
- **ECR:** Stores the last 3 container images (Free tier: 500MB)
