variable "project_id" {
  description = "The GCP Project ID where resources will be deployed."
  type        = string
}

variable "region" {
  description = "The GCP region to deploy resources into."
  type        = string
  default     = "us-central1"
}
