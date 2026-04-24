resource "google_service_account" "api_sa" {
  account_id   = var.api_sa_name
  display_name = "Biometric API Service Account"
  description  = "Service account used by the Agentic RAG FastAPI backend."
  project      = var.project_id
}

# Grant BigQuery Data Viewer to the API SA
resource "google_project_iam_member" "api_bq_viewer" {
  project = var.project_id
  role    = "roles/bigquery.dataViewer"
  member  = "serviceAccount:${google_service_account.api_sa.email}"
}

# Grant BigQuery Job User (required to run queries)
resource "google_project_iam_member" "api_bq_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.api_sa.email}"
}

# Grant GCS Object Viewer (for reading parquet files in the external tables)
resource "google_project_iam_member" "api_gcs_viewer" {
  project = var.project_id
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${google_service_account.api_sa.email}"
}
