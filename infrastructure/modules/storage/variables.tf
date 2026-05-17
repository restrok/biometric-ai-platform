variable "project_id" {
  description = "The GCP Project ID."
  type        = string
}

variable "region" {
  description = "The GCP region."
  type        = string
}

variable "bucket_name" {
  description = "The GCS bucket name for the data lake."
  type        = string
}

variable "state_bucket_name" {
  description = "The GCS bucket name for Terraform state."
  type        = string
  default     = ""
}
