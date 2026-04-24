output "bucket_name" {
  value = google_storage_bucket.datalake.name
}

output "dataset_id" {
  value = google_bigquery_dataset.biometric_dataset.dataset_id
}
