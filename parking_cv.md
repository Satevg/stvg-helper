# Plan: Replace Claude Vision with YOLOv8n Vehicle Detection

## Context

The current parking feature sends each camera JPEG to Claude Haiku Vision to ask "is there a free parking spot?" — this gives unreliable/false results. We're replacing it with local YOLOv8n (ONNX) vehicle detection using a **coverage ratio** approach: detect all vehicles in the frame, calculate the fraction of frame area occupied by vehicle bounding boxes, and if coverage is below a threshold, report a free spot. No per-camera calibration or manual spot marking needed.

Because adding `onnxruntime` (~100 MB) exceeds the Lambda zip 250 MB limit, we're switching to **container image Lambda** deployment (10 GB limit, same free tier).

---

## Implementation Steps

### 1. Export YOLOv8n ONNX model

- One-time local step: `pip install ultralytics && yolo export model=yolov8n.pt format=onnx imgsz=640`
- Commit resulting `models/yolov8n.onnx` (~6 MB) to repo
- Add `models/` to `.gitattributes` or document the export in CLAUDE.md

### 2. Create `bot/detector.py` — vehicle detection module

New file with:
- `_get_session()` — `@lru_cache` ONNX Runtime `InferenceSession` (loaded once per warm Lambda)
- `preprocess(jpeg_bytes)` — resize to 640x640, normalize, CHW transpose → numpy tensor
- `postprocess(output, orig_size)` — parse YOLOv8 output `[1, 84, 8400]`, filter vehicle classes (COCO IDs 2,3,5,7 = car, motorcycle, bus, truck), confidence threshold ~0.35, NMS in pure numpy (no OpenCV dependency)
- `detect_vehicles(jpeg_bytes) -> tuple[float, list[Detection]]` — returns `(coverage_ratio, detections)` where coverage = sum of bbox areas / image area
- `Detection` NamedTuple: `x1, y1, x2, y2, confidence, class_id`

### 3. Modify `bot/parking.py` — replace Claude Vision with detector

- Remove: `anthropic` import, `get_anthropic_api_key()`, `_is_free()` (Claude Vision call), `_GRID_CELLS`, `_CELL_RE`
- Replace `_is_free()` with new function using `detector.detect_vehicles()`:
  ```python
  COVERAGE_THRESHOLD = 0.40  # below this → free spot likely

  def _is_free(jpeg_bytes: bytes) -> tuple[bool, list[Detection]]:
      coverage, detections = detect_vehicles(jpeg_bytes)
      return coverage < COVERAGE_THRESHOLD, detections
  ```
- `PARKING_CAMERAS` stays as-is (no `max_vehicles` field needed with coverage approach)
- Replace `_annotate_jpeg()` — draw bounding boxes around detected vehicles instead of grid cell overlay; highlight the largest empty region
- Update `parking_handler()`: remove `AsyncAnthropic` client creation, call new `_is_free(jpeg)`, log coverage ratio per camera for monitoring/tuning
- SSM_ANTHROPIC_API_KEY_PARAM can be removed from this file (still used in handler.py)

### 4. Create `Dockerfile`

```dockerfile
FROM public.ecr.aws/lambda/python:3.12
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv export --frozen --no-dev --no-emit-project | pip install -r /dev/stdin
COPY bot/ ${LAMBDA_TASK_ROOT}/
COPY models/ ${LAMBDA_TASK_ROOT}/models/
CMD ["handler.lambda_handler"]
```

Note: PyAV in the Lambda Python base image should work since it bundles its own FFmpeg libs. If not, add `RUN dnf install -y ...` for FFmpeg shared libs.

### 5. Create `terraform/ecr.tf`

- `aws_ecr_repository` for `stvg-helper-bot`
- `aws_ecr_lifecycle_policy` keeping only last 3 images (keeps ECR storage under 500 MB free tier)

### 6. Modify `terraform/lambda.tf`

- Switch from zip/S3 to container image: `package_type = "Image"`, `image_uri` from ECR
- Remove: `handler`, `runtime`, `s3_bucket`, `s3_key`, `source_code_hash`
- Increase `memory_size` to 512 MB (ONNX Runtime + model loading; still well within free tier: 400K GB-s / 0.5 GB = 800K seconds/month)
- Increase `timeout` to 60 seconds (local inference is faster than API calls, but allow headroom)
- Remove `SSM_ANTHROPIC_API_KEY_PARAM` from environment variables (parking no longer needs it; handler.py fetches it from SSM directly)

### 7. Modify `terraform/s3.tf` — remove or keep Lambda artifact bucket

The S3 artifact bucket (`stvg-helper-lambda-artifacts`) is no longer needed for deployment. Can be removed or kept for other uses.

### 8. Replace `scripts/package.sh` with `scripts/deploy.sh`

Docker build + ECR push script:
- `aws ecr get-login-password` → `docker login`
- `docker build -t stvg-helper-bot .`
- `docker tag` + `docker push` to ECR

### 9. Update `Makefile`

- `package` target → calls `scripts/deploy.sh` (builds + pushes container image)
- `deploy` target → `terraform apply` + `aws lambda update-function-code --image-uri ...`
- `release` → `package` then `deploy`

### 10. Add `onnxruntime` and `numpy` to `pyproject.toml`

Add to `[project.dependencies]`:
- `onnxruntime` (CPU-only)
- `numpy`

Run `uv lock` to update lockfile.

### 11. Update tests

**`tests/test_parking.py`:**
- Remove: `TestCellRe`, `TestAnnotateJpeg` (grid-based), `TestIsFree` (Claude Vision mocks)
- Add: tests for new coverage-based `_is_free()`, new annotation function

**New `tests/test_detector.py`:**
- Test `preprocess()` output shape and normalization
- Test `postprocess()` with synthetic YOLO output arrays
- Test `count_vehicles()` with mocked ONNX session
- Test NMS logic

### 12. Create `scripts/calibrate.py` (dev-only helper)

Script that connects to Watcher, fetches current snapshots from all cameras, runs the detector, and prints coverage ratio per camera. Useful for tuning `COVERAGE_THRESHOLD`.

### 13. Update `CLAUDE.md`

Document: new detection approach, container image deployment, model export process, calibration script, ECR lifecycle.

---

## Key files to modify

| File | Action |
|------|--------|
| `bot/parking.py` | Replace Claude Vision with detector-based coverage check |
| `bot/detector.py` | **New** — YOLOv8n ONNX inference module |
| `models/yolov8n.onnx` | **New** — pre-trained model (~6 MB) |
| `Dockerfile` | **New** — container image build |
| `terraform/lambda.tf` | Switch to container image, bump memory/timeout |
| `terraform/ecr.tf` | **New** — ECR repository + lifecycle policy |
| `scripts/package.sh` → `scripts/deploy.sh` | Replace zip packaging with Docker build + push |
| `Makefile` | Update build/deploy targets |
| `pyproject.toml` | Add onnxruntime, numpy |
| `tests/test_parking.py` | Update for new detection logic |
| `tests/test_detector.py` | **New** — detector unit tests |
| `scripts/calibrate.py` | **New** — dev-only threshold tuning tool |
| `CLAUDE.md` | Document new architecture |

## Verification

1. **Unit tests**: `make test` — all detector and parking tests pass
2. **Lint**: `make lint` — black, isort, mypy clean
3. **Local Docker build**: `docker build -t stvg-helper-bot .` succeeds
4. **Calibration**: Run `scripts/calibrate.py` to verify vehicle detection works on real camera snapshots and coverage ratios are sensible
5. **Deploy**: `make release` — pushes image to ECR, updates Lambda
6. **E2E**: Send "Parking" in Telegram, verify bot responds with a camera image showing detected vehicles (or "not found")
7. **CloudWatch**: Check logs for coverage ratio values per camera to tune threshold