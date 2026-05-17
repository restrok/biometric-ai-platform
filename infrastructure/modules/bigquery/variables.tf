variable "project_id" {
  description = "The ID of the project in which to provision resources."
  type        = string
}

variable "region" {
  description = "The region in which to provision resources."
  type        = string
}

variable "dataset_name" {
  description = "The name of the BigQuery dataset."
  type        = string
}
