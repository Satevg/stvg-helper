resource "aws_s3_bucket" "lambda_artifacts" {
  bucket = "stvg-helper-lambda-artifacts"
}

resource "aws_s3_bucket_public_access_block" "lambda_artifacts" {
  bucket                  = aws_s3_bucket.lambda_artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_object" "lambda_zip" {
  bucket = aws_s3_bucket.lambda_artifacts.id
  key    = "lambda.zip"
  source = local.lambda_zip_path
  etag   = local.lambda_zip_exists ? filemd5(local.lambda_zip_path) : null
}
