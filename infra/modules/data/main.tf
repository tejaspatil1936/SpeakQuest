# Single DynamoDB table (system design §7): on-demand, PITR off, deletion
# protection off so `terraform destroy` always succeeds. ANALYSIS# items
# expire through the ttl attribute (14 days).
resource "aws_dynamodb_table" "main" {
  name                        = var.name_prefix
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "pk"
  range_key                   = "sk"
  deletion_protection_enabled = false

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = false
  }

  server_side_encryption {
    # AWS-owned key: no KMS key to delete or pay for.
    enabled = false
  }
}
