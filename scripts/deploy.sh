#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AWS_REGION="${AWS_REGION:-eu-central-1}"
REPO_NAME="stvg-helper-bot"

echo "Fetching ECR repository URL from Terraform..."
ECR_REPO_URL=$(terraform -chdir="$PROJECT_ROOT/terraform" output -raw ecr_repository_url)
IMAGE_URI="${ECR_REPO_URL}:latest"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo "Logging in to ECR..."
aws ecr get-login-password --region "${AWS_REGION}" | docker login --username AWS --password-stdin "${ECR_REGISTRY}"

echo "Building Docker image..."
docker build --platform linux/amd64 --provenance=false -t "${REPO_NAME}" "${PROJECT_ROOT}"

echo "Tagging and pushing image to ECR..."
docker tag "${REPO_NAME}:latest" "${IMAGE_URI}"
docker push "${IMAGE_URI}"

echo "Image pushed: ${IMAGE_URI}"
