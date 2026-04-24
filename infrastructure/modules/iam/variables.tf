variable "project_id" {
  description = "The GCP Project ID."
  type        = string
}

variable "api_sa_name" {
  description = "The name of the Service Account for the FastAPI application."
  type        = string
  default     = "biometric-api-sa"
}
