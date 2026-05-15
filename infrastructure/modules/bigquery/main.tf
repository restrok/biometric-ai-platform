resource "google_bigquery_dataset" "biometric_dataset" {
  dataset_id                 = var.dataset_name
  friendly_name              = "Biometric AI Data"
  description                = "Dataset containing biometric facts for AI RAG."
  location                   = var.region
  delete_contents_on_destroy = true
}

# 🛡️ Quota Management to Protect Free Tier
# Limits the "Query usage per day" (QueryUsagePerDay) to 1TB.
# BigQuery free tier is 1TB of querying per month, so setting a daily limit
# lower than this or exactly at this helps manage accidental runaways.
# Adjust the value as needed (1024 GB = 1TB approx). Here we use 100GB/day.

resource "google_cloud_quotas_quota_preference" "bigquery_query_usage" {
  service  = "bigquery.googleapis.com"
  parent   = "projects/${var.project_id}"
  quota_id = "QueryUsagePerDay"
  ignore_safety_checks = "QUOTA_DECREASE_PERCENTAGE_TOO_HIGH"
  quota_config {
    preferred_value = floor(1024 * 1024 / 30)
  }
}
