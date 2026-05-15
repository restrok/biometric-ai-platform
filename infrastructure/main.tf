terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.0"
    }
  }

  backend "gcs" {}
}

provider "google" {
  project               = var.project_id
  region                = var.region
  user_project_override = true
  billing_project       = var.project_id
}

provider "google-beta" {
  project               = var.project_id
  region                = var.region
  user_project_override = true
  billing_project       = var.project_id
}

module "storage" {
  source            = "./modules/storage"
  project_id        = var.project_id
  region            = var.region
  bucket_name       = var.datalake_bucket_name
  state_bucket_name = "tf-state-${var.project_id}"
}

module "bigquery" {
  source       = "./modules/bigquery"
  project_id   = var.project_id
  region       = var.region
  dataset_name = var.dataset_name
}

module "iam" {
  source      = "./modules/iam"
  project_id  = var.project_id
  api_sa_name = "biometric-api-dev-sa"
}

module "secrets" {
  source     = "./modules/secrets"
  project_id = var.project_id
}

module "billing" {
  source             = "./modules/billing"
  project_id         = var.project_id
  billing_account_id = var.billing_account_id
}

