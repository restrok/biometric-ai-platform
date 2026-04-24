variable "project_id" {
  description = "The GCP Project ID where resources will be deployed."
  type        = string
}

variable "billing_account_id" {
  description = "The ID of the billing account to associate with the budget."
  type        = string
}

variable "region" {
  description = "The GCP region to deploy resources into."
  type        = string
  default     = "us-central1"
}

variable "datalake_bucket_name" {
  description = "Name of the GCS bucket for the datalake."
  type        = string
}

variable "dataset_name" {
  description = "Name of the BigQuery dataset."
  type        = string
  default     = "biometric_data"
}
