variable "project_id" {
  description = "The GCP Project ID."
  type        = string
}

variable "region" {
  description = "The GCP region."
  type        = string
}

variable "dataset_name" {
  description = "The BigQuery dataset name."
  type        = string
  default     = "biometric_data"
}

variable "bucket_name" {
  description = "The GCS bucket name for the data lake."
  type        = string
}
