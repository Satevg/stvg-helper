# STVG Helper Bot

Personal Telegram bot hosted on AWS Lambda.

## Tech Stack

-   **Bot**: Python 3.12, python-telegram-bot v20+, Anthropic SDK, requests
-   **AI**: Free-form messages forwarded to Claude (`claude-haiku-4-5-20251001`)
-   **Vehicle detection**: YOLOv8n ONNX (local inference, no API calls) via `onnxruntime` + `numpy`
-   **Dependencies**: uv (`pyproject.toml`); runtime deps bundled in container image, dev deps (boto3, black, isort, mypy, types-requests) local-only
-   **Infrastructure**: Terraform, AWS (Lambda container image, ECR, API Gateway v2, SSM Parameter Store)
-   **State**: Terraform S3 backend with DynamoDB locking

## Project Structure

-   `bot/handler.py` — Lambda entrypoint, routing, Claude handler
-   `bot/parking.py` — Flussonic Watcher integration and parking snapshot handler
-   `bot/detector.py` — YOLOv8n ONNX vehicle detection module
-   `models/yolov8n.onnx` — Pre-trained YOLOv8n model (~6 MB, one-time export)
-   `Dockerfile` — Container image build for Lambda
-   `terraform/` — Infrastructure as code
-   `scripts/` — Build and deployment scripts

## Development

### First-time setup

```bash
# 1. Install local dev dependencies
uv sync

# 2. Export the YOLOv8n ONNX model (one-time)
pip install ultralytics
yolo export model=yolov8n.pt format=onnx imgsz=640
mkdir -p models && mv yolov8n.onnx models/

# 3. Create S3 bucket + DynamoDB table for Terraform state (once only)
make bootstrap

# 4. Initialise Terraform
make init

# 5. Create the ECR repository first (Lambda image must exist before full apply)
terraform -chdir=terraform apply -target=aws_ecr_repository.bot

# 6. Build and push the container image
make package

# 7. Deploy remaining infrastructure (Lambda + everything else)
terraform -chdir=terraform apply

# 8. Set the Telegram bot token
aws ssm put-parameter --name "/stvg-helper/telegram-bot-token" \
  --value "YOUR_TOKEN" --type SecureString --overwrite

# 9. Set the Anthropic API key (console.anthropic.com → API Keys)
aws ssm put-parameter --name "/stvg-helper/anthropic-api-key" \
  --value "YOUR_ANTHROPIC_API_KEY" --type SecureString --overwrite

# 10. Set Flussonic Watcher credentials (video.unet.by)
aws ssm put-parameter --name "/stvg-helper/watcher-username" \
  --value "YOUR_WATCHER_USERNAME" --type SecureString --overwrite
aws ssm put-parameter --name "/stvg-helper/watcher-password" \
  --value "YOUR_WATCHER_PASSWORD" --type SecureString --overwrite

# 11. Register the webhook with Telegram
make webhook BOT_TOKEN=YOUR_TOKEN
```

### Subsequent deploys

```bash
make release
```

### Tuning the detection threshold

```bash
# Fetch live snapshots and print coverage ratios per camera
YOLO_MODEL_PATH=models/yolov8n.onnx uv run scripts/calibrate.py
```

Adjust `COVERAGE_THRESHOLD` in `bot/parking.py` based on the output.

## Architecture Notes

-   **Event loop singleton**: `_loop` and `_application` are module-level singletons intentionally kept alive across warm Lambda invocations. Do not close the event loop or rebuild the application per request — the httpx client inside `Application` is bound to the event loop and breaks if the loop is recreated.
-   **`AnyApplication` type alias**: `Application` from python-telegram-bot is generic with 6 type parameters; `AnyApplication = Application[Any, Any, Any, Any, Any, Any]` is used throughout to satisfy mypy strict mode.
-   **Message routing**: menu button labels ("Hello", "Parking") are matched first by `menu_button_handler`; all other non-command text falls through to `claude_handler`. Always register specific handlers before the catch-all.
-   **Claude API**: uses `AsyncAnthropic` client with `claude-haiku-4-5-20251001`. API key stored in SSM at `/stvg-helper/anthropic-api-key`.
-   **Parking feature**: `bot/parking.py` searches for a free parking spot using local YOLOv8n vehicle detection. Flow: login to Watcher → fetch all cameras → match cameras from `PARKING_CAMERAS` config → fetch snapshots building-by-building in priority order → run `detect_vehicles()` on each JPEG → if vehicle coverage ratio is below `COVERAGE_THRESHOLD` (0.40), report free spot and send annotated image. The annotated image overlays a 6×4 grid; cells with no vehicle overlap are highlighted green so the user can see where to park. Credentials in SSM at `/stvg-helper/watcher-username` and `/stvg-helper/watcher-password`.
-   **Vehicle detection** (`bot/detector.py`): `_get_session()` loads the YOLOv8n ONNX model once per warm Lambda (LRU-cached). `detect_vehicles(jpeg_bytes)` returns `(coverage_ratio, detections)` where coverage = sum of vehicle bounding-box areas / image area (capped at 1.0). COCO vehicle classes: car (2), motorcycle (3), bus (5), truck (7). Confidence threshold: 0.35. NMS IoU threshold: 0.45. Model path defaults to `models/yolov8n.onnx` relative to `detector.py`; override with `YOLO_MODEL_PATH` env var.
-   **YOLOv8n ONNX model**: export once with `yolo export model=yolov8n.pt format=onnx imgsz=640`. Commit `models/yolov8n.onnx` (~6 MB) to the repo. The model is copied into the container at `${LAMBDA_TASK_ROOT}/models/yolov8n.onnx` by the Dockerfile.
-   **Coverage threshold**: `COVERAGE_THRESHOLD = 0.40` in `bot/parking.py`. If total vehicle bounding-box area exceeds 40% of the frame, the spot is considered occupied. Tune using `scripts/calibrate.py` against live camera snapshots. Coverage ratio per camera is logged at INFO level for CloudWatch monitoring.
-   **Parking camera config** (`PARKING_CAMERAS` in `bot/parking.py`): buildings and camera numbers checked in priority order. Авиационная 8 → Авиационная 10 → Б. Райт 1 → Б. Райт 3 → Б. Райт 5 → Б. Райт 7 → Яковлева 1. Search stops as soon as any camera reports a free spot.
-   **Camera title matching**: `find_camera()` normalises titles with `_norm()` (lowercase, collapse `.` and whitespace to single space) so "Б.Райт 1" and "Б. Райт 1" both match. Looks for camera title field (`title`) containing both the building name and "Камера NN" (zero-padded). If a camera is not found, a WARNING is logged with the building+number so the API title format can be verified in CloudWatch.
-   **Snapshot fetching**: `_fetch_jpeg()` fetches `preview.mp4` from the streaming server (`https://{cam.streamer_hostname}/{cam.name}/preview.mp4?token={cam.playback_config.token}`) and decodes the first H.264 frame to JPEG using PyAV + Pillow. `preview.jpg` and `screenshot.jpg` both return 404 on this Watcher instance (thumbnails disabled). Watcher API snapshot endpoints (`/vsaas/api/v2/cameras/{id}/snapshot`, `/vsaas/api/v2/streams/{name}/snapshot`) also do not work (404/400).
-   **Flussonic Watcher API**: login via `POST /vsaas/api/v2/auth/login` → session key in `X-Vsaas-Session` header; camera list via `GET /vsaas/api/v2/cameras`. Camera fields used: `name` (stream identifier, used in URLs), `title` (human-readable, used for matching), `streamer_hostname`, `playback_config.token`. Note: use `streamer_hostname`, not `stream_status.server`.
-   **Container image deployment**: `Dockerfile` uses `public.ecr.aws/lambda/python:3.12` base image. Dependencies installed via `uv export | pip install`. Bot code copied from `bot/` and model from `models/`. Container image stored in ECR (`stvg-helper-bot` repository); Lambda configured with `package_type = "Image"`. ECR lifecycle policy keeps only the last 3 images (stays within 500 MB free tier). **First-time deploy requires creating the ECR repo before the full `terraform apply`** — see setup steps above. `scripts/deploy.sh` builds with `--platform linux/amd64 --provenance=false` to produce a Docker V2 manifest; omitting `--provenance=false` causes BuildKit to emit an OCI manifest list which Lambda rejects.
-   **Lambda memory**: 512 MB (increased from 256 MB to accommodate ONNX Runtime + model loading; 400K GB-s free tier = ~800K seconds/month at 0.5 GB).
-   **ECR lifecycle**: `terraform/ecr.tf` retains only the 3 most recent images, keeping ECR storage well within the 500 MB free tier.

## Conventions

-   Python: snake_case, type hints where practical
-   Terraform: one resource type per file, descriptive resource names
-   All secrets via SSM Parameter Store, never hardcoded
-   Dependencies: add runtime deps to `[project.dependencies]`, dev-only deps to `[dependency-groups] dev` in `pyproject.toml`; commit `uv.lock`
-   Linting: run `make lint` before committing; use `make black-fix` / `make isort-fix` to auto-fix formatting
-   When adding additional AWS resources, check if we're fitting into AWS free-tier limits
