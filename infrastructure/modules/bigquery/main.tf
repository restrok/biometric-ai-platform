resource "google_bigquery_dataset" "biometric_dataset" {
  dataset_id                 = var.dataset_name
  friendly_name              = "Biometric AI Data"
  description                = "Dataset containing biometric facts for AI RAG."
  location                   = var.region
  delete_contents_on_destroy = true
}

# 🛡️ Quota Management to Protect Free Tier
# Manages the existing QueryUsagePerDay quota preference in GCP
resource "google_cloud_quotas_quota_preference" "bigquery_query_usage" {
  name                 = "654e8a37-cc6a-42a5-b3b7-2d25f2a3fc97"
  service              = "bigquery.googleapis.com"
  parent               = "projects/${var.project_id}"
  quota_id             = "QueryUsagePerDay"
  ignore_safety_checks = "QUOTA_DECREASE_PERCENTAGE_TOO_HIGH"
  quota_config {
    preferred_value = 34952
  }
}
