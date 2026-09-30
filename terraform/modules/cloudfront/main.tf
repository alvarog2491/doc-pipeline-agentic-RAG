variable "env" {
  type = string
}

variable "alb_dns_name" {
  description = "Plaintext HTTP origin: the ALB has no TLS listener and no ACM certificate."
  type        = string
}

# CloudFront standard access logs. The bucket needs ACLs enabled (BucketOwnerPreferred) so
# the CloudFront log-delivery group can write objects the account still owns.
resource "aws_s3_bucket" "logs" {
  bucket_prefix = "doc-pipeline-${var.env}-cf-logs-"
  force_destroy = true
}

resource "aws_s3_bucket_ownership_controls" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    object_ownership = "BucketOwnerPreferred"
  }
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket                  = aws_s3_bucket.logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "logs" {
  bucket = aws_s3_bucket.logs.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    id     = "expire-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = 90
    }

    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }
}

data "aws_iam_policy_document" "logs_tls" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.logs.arn, "${aws_s3_bucket.logs.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "logs" {
  bucket = aws_s3_bucket.logs.id
  policy = data.aws_iam_policy_document.logs_tls.json
}

# Managed policies: CachingDisabled and AllViewerExceptHostHeader.
locals {
  caching_disabled_policy_id     = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
  all_viewer_except_host_id      = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
  all_viewer_except_host_comment = "Forward every viewer header except Host, which must stay the origin domain."
}

# Gives the API an https://xxxx.cloudfront.net endpoint with a default TLS certificate. The
# hosted frontend runs over HTTPS, so browsers refuse the ALB's plaintext origin. Server-Sent
# Events pass straight through: nothing is cached, and the API's 15 s keep-alive comments
# stay well inside the origin read timeout, so a long-thinking guide never drops.
resource "aws_cloudfront_distribution" "this" {
  enabled         = true
  comment         = "doc-pipeline-${var.env} REST + SSE API"
  http_version    = "http2and3"
  price_class     = "PriceClass_100" # US + Europe only
  is_ipv6_enabled = true

  origin {
    origin_id   = "alb"
    domain_name = var.alb_dns_name

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "http-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 60
      origin_keepalive_timeout = 60
    }
  }

  default_cache_behavior {
    target_origin_id         = "alb"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = local.caching_disabled_policy_id
    origin_request_policy_id = local.all_viewer_except_host_id
    compress                 = false # compression buffers; SSE must flush per event
  }

  logging_config {
    bucket          = aws_s3_bucket.logs.bucket_regional_domain_name
    prefix          = "cloudfront/"
    include_cookies = false
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  depends_on = [aws_s3_bucket_ownership_controls.logs]
}

output "domain_name" {
  value = aws_cloudfront_distribution.this.domain_name
}

output "distribution_id" {
  value = aws_cloudfront_distribution.this.id
}
