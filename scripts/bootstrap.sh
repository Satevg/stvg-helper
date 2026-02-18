#!/usr/bin/env bash
# Creates the S3 bucket and DynamoDB table for Terraform remote state.
# Run this ONCE before the first `terraform init`.
set -euo pipefail

BUCKET="stvg-helper-tfstate"
DYNAMODB_TABLE="stvg-helper-tfstate-lock"
REGION="${AWS_REGION:-eu-central-1}"

echo "==> Bootstrapping Terraform state backend in region: $REGION"

# --- S3 bucket ---
if aws s3api head-bucket --bucket "$BUCKET" --region "$REGION" 2>/dev/null; then
  echo "    S3 bucket '$BUCKET' already exists, skipping."
else
  echo "    Creating S3 bucket '$BUCKET'..."
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION"
  fi

  echo "    Enabling versioning..."
  aws s3api put-bucket-versioning --bucket "$BUCKET" \
    --versioning-configuration Status=Enabled

  echo "    Enabling server-side encryption..."
  aws s3api put-bucket-encryption --bucket "$BUCKET" \
    --server-side-encryption-configuration '{
      "Rules": [{
        "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
        "BucketKeyEnabled": true
      }]
    }'

  echo "    Blocking public access..."
  aws s3api put-public-access-block --bucket "$BUCKET" \
    --public-access-block-configuration \
      "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
fi

# --- DynamoDB table ---
if aws dynamodb describe-table --table-name "$DYNAMODB_TABLE" --region "$REGION" 2>/dev/null; then
  echo "    DynamoDB table '$DYNAMODB_TABLE' already exists, skipping."
else
  echo "    Creating DynamoDB table '$DYNAMODB_TABLE'..."
  aws dynamodb create-table \
    --table-name "$DYNAMODB_TABLE" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION"

  echo "    Waiting for table to become active..."
  aws dynamodb wait table-exists --table-name "$DYNAMODB_TABLE" --region "$REGION"
fi

echo ""
echo "==> Bootstrap complete. Run 'terraform init' next."
