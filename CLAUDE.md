# STVG Helper Bot

Personal Telegram bot hosted on AWS Lambda.

## Tech Stack

-   **Bot**: Python 3.12, python-telegram-bot v20+, Anthropic SDK, requests
-   **AI**: Free-form messages forwarded to Claude (`claude-haiku-4-5-20251001`)
-   **Dependencies**: uv (`pyproject.toml`); runtime deps bundled in Lambda zip, dev deps (boto3, black, isort, mypy, types-requests) local-only
-   **Infrastructure**: Terraform, AWS (Lambda, API Gateway v2, SSM Parameter Store)
-   **State**: Terraform S3 backend with DynamoDB locking

## Project Structure

-   `bot/handler.py` — Lambda entrypoint, routing, Claude handler
-   `bot/parking.py` — Flussonic Watcher integration and parking snapshot handler
-   `terraform/` — Infrastructure as code
-   `scripts/` — Build and deployment scripts

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
aws ssm put-parameter --name "/stvg-helper/telegram-bot-token" 
  --value "YOUR_TOKEN" --type SecureString --overwrite

# 5. Set the Anthropic API key (console.anthropic.com → API Keys)
aws ssm put-parameter --name "/stvg-helper/anthropic-api-key" 
  --value "YOUR_ANTHROPIC_API_KEY" --type SecureString --overwrite

# 6. Set Flussonic Watcher credentials (video.unet.by)
aws ssm put-parameter --name "/stvg-helper/watcher-username" 
  --value "YOUR_WATCHER_USERNAME" --type SecureString --overwrite
aws ssm put-parameter --name "/stvg-helper/watcher-password" 
  --value "YOUR_WATCHER_PASSWORD" --type SecureString --overwrite

# 7. Register the webhook with Telegram
make webhook BOT_TOKEN=YOUR_TOKEN
```

### Subsequent deploys

```bash
make release
```

## Architecture Notes

-   **Event loop singleton**: `_loop` and `_application` are module-level singletons intentionally kept alive across warm Lambda invocations. Do not close the event loop or rebuild the application per request — the httpx client inside `Application` is bound to the event loop and breaks if the loop is recreated.
-   **`AnyApplication` type alias**: `Application` from python-telegram-bot is generic with 6 type parameters; `AnyApplication = Application[Any, Any, Any, Any, Any, Any]` is used throughout to satisfy mypy strict mode.
-   **Message routing**: menu button labels ("Hello", "Parking") are matched first by `menu_button_handler`; all other non-command text falls through to `claude_handler`. Always register specific handlers before the catch-all.
-   **Claude API**: uses `AsyncAnthropic` client with `claude-haiku-4-5-20251001`. API key stored in SSM at `/stvg-helper/anthropic-api-key`.
-   **Parking feature**: `bot/parking.py` searches for a free parking spot using Claude Vision. Flow: login to Watcher → fetch all cameras → match cameras from `PARKING_CAMERAS` config → fetch all JPEG snapshots in parallel → analyze building-by-building in priority order with Claude Vision (`_is_free`) → reply with the first camera image where a free spot is detected (or "not found" if none). Credentials in SSM at `/stvg-helper/watcher-username` and `/stvg-helper/watcher-password`. Anthropic key re-fetched from SSM at `/stvg-helper/anthropic-api-key` (same param as `handler.py`, no extra Terraform needed).
-   **Parking camera config** (`PARKING_CAMERAS` in `bot/parking.py`): buildings and camera numbers checked in priority order. Авиационная 8 → Авиационная 10 → Б. Райт 1 → Б. Райт 3 → Б. Райт 5 → Б. Райт 7 → Яковлева 1. Search stops as soon as any camera reports a free spot.
-   **Camera title matching**: `find_camera()` normalises titles with `_norm()` (lowercase, collapse `.` and whitespace to single space) so "Б.Райт 1" and "Б. Райт 1" both match. Looks for camera title field (`title`) containing both the building name and "Камера NN" (zero-padded). If a camera is not found, a WARNING is logged with the building+number so the API title format can be verified in CloudWatch.
-   **Snapshot fetching**: `_fetch_jpeg()` fetches `preview.mp4` from the streaming server (`https://{cam.streamer_hostname}/{cam.name}/preview.mp4?token={cam.playback_config.token}`) and decodes the first H.264 frame to JPEG using PyAV + Pillow. `preview.jpg` and `screenshot.jpg` both return 404 on this Watcher instance (thumbnails disabled). Watcher API snapshot endpoints (`/vsaas/api/v2/cameras/{id}/snapshot`, `/vsaas/api/v2/streams/{name}/snapshot`) also do not work (404/400).
-   **Flussonic Watcher API**: login via `POST /vsaas/api/v2/auth/login` → session key in `X-Vsaas-Session` header; camera list via `GET /vsaas/api/v2/cameras`. Camera fields used: `name` (stream identifier, used in URLs), `title` (human-readable, used for matching), `streamer_hostname`, `playback_config.token`. Note: use `streamer_hostname`, not `stream_status.server`.
-   **Lambda packaging**: `scripts/package.sh` copies all `bot/*.py` files into the zip. Zip is uploaded to S3 (`stvg-helper-lambda-artifacts`) by Terraform; Lambda deploys from S3 (direct upload limit is 50 MB, package with `av`+`Pillow` exceeds this).
-   **Lambda memory**: 256 MB (increased from 128 MB to accommodate PyAV/FFmpeg library loading).

## Conventions

-   Python: snake_case, type hints where practical
-   Terraform: one resource type per file, descriptive resource names
-   All secrets via SSM Parameter Store, never hardcoded
-   Dependencies: add runtime deps to `[project.dependencies]`, dev-only deps to `[dependency-groups] dev` in `pyproject.toml`; commit `uv.lock`
-   Linting: run `make lint` before committing; use `make black-fix` / `make isort-fix` to auto-fix formatting
-   When adding additional AWS resources, check if we're fitting into AWS free-tier limits