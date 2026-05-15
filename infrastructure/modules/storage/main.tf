# Data Lake Bucket
resource "google_storage_bucket" "datalake" {
  name          = var.bucket_name
  location      = var.region
  force_destroy = true # Useful for dev environments

  uniform_bucket_level_access = true

  lifecycle_rule {
    condition {
      age            = 180
      matches_prefix = ["reports/"]
      matches_suffix = [".md"]
    }
    action {
      type = "Delete"
    }
  }

  lifecycle_rule {
    condition {
      age = 365
    }
    action {
      type = "Delete"
    }
  }
}

# BigQuery Dataset
resource "google_bigquery_dataset" "biometric_dataset" {
  dataset_id                 = var.dataset_name
  friendly_name              = "Biometric AI Data"
  description                = "Dataset containing biometric facts for AI RAG."
  location                   = var.region
  delete_contents_on_destroy = true # Useful for dev environments
}

# 🗄️ Terraform State Bucket (Optional if managed by this module)
resource "google_storage_bucket" "tf_state" {
  count         = var.state_bucket_name != "" ? 1 : 0
  name          = var.state_bucket_name
  location      = var.region
  force_destroy = false # Protect the state!

  versioning {
    enabled = true
  }

  uniform_bucket_level_access = true
}
