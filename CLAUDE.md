# STVG Helper Bot - Architecture & Standards

Personal Telegram bot hosted on AWS Lambda.

## Tech Stack

-   **Bot**: Python 3.12, python-telegram-bot v21.10, Anthropic SDK, requests
-   **AI**: Free-form messages forwarded to Claude (`claude-haiku-4-5-20251001`)
-   **Vehicle detection**: YOLOv8n ONNX (local inference) via `onnxruntime` + `numpy`
-   **Data Store**: DynamoDB (Heatmap state, confirmed slots)
-   **Infrastructure**: Terraform, AWS (Lambda container image, ECR, API Gateway v2, SSM, EventBridge)

## Project Structure

-   `bot/handler.py` — Lambda entrypoint, EventBridge routing, Claude integration
-   `bot/parking.py` — Flussonic Watcher integration and parking logic
-   `bot/heatmap.py` — Autonomous learning engine (clustering/DynamoDB)
-   `bot/detector.py` — YOLOv8n ONNX vehicle detection module
-   `models/yolov8n.onnx` — Pre-trained YOLOv8n model
-   `terraform/` — Infrastructure as code

## Key Systems

### Autonomous Parking (Heatmap)
The system learns parking spots through passive observation:
1. **Clustering**: Detections are merged into clusters based on Euclidean distance (`PROXIMITY_THRESHOLD = 0.05`).
2. **Confirmation**: A slot is only trusted after being seen `CONFIRMATION_THRESHOLD = 3` times.
3. **Detection**: A spot is "FREE" if a confirmed slot has no current vehicle overlap.
4. **Drift**: Slot coordinates move toward new detections via a moving average, refining accuracy over time.
5. **Garbage Collection**: Slots not seen for 7 days are pruned from DynamoDB.

### Automated Learning (EventBridge)
EventBridge triggers the Lambda every 5 minutes. The bot picks **2 random cameras** per ping to scan and update the heatmap. This ensures the entire network of ~45 cameras is updated ~12 times a day automatically while staying within the AWS Free Tier.

### Event Loop Management
- **Singletons**: `_loop` and `_application` are kept alive across warm Lambda invocations. 
- **Warmup Logic**: In `lambda_handler`, the `aws.events` source triggers `update_heatmap_background()` to perform background learning.

## Development Standards

- **Formatting**: Black (120 chars), Isort (Black profile). Run `make black-fix` / `make isort-fix`.
- **Typing**: Strict Mypy. All new functions must have type hints.
- **Testing**: Pytest. Use `tests/test_background.py` and `tests/test_heatmap.py` for verifying learning logic.
- **Infrastructure**: All AWS resources must fit within the Free Tier.
- **Secrets**: Use SSM Parameter Store. Never hardcode tokens or credentials.

## Deployment

1. `make package` - Build and push Docker image.
2. `terraform apply` - Deploy infra (first time: target the ECR repo first).
3. `make release` - Standard update (build + deploy).
