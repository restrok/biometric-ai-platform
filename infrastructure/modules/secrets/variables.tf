variable "project_id" {
  description = "The GCP project ID"
  type        = string
}

variable "secret_ids" {
  description = "List of secret IDs to create"
  type        = list(string)
  default     = ["aistudio-api-key", "garmin-tokens"]
}
