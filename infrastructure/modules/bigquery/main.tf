resource "google_bigquery_dataset" "biometric_dataset" {
  dataset_id                 = var.dataset_name
  friendly_name              = "Biometric AI Data"
  description                = "Dataset containing biometric facts for AI RAG."
  location                   = var.region
  delete_contents_on_destroy = true
}


