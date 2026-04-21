terraform {
  required_version = ">= 1.5.0"
  
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  backend "local" {
    path = "terraform.tfstate"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

module "storage" {
  source       = "./modules/storage"
  project_id   = var.project_id
  region       = var.region
  bucket_name  = var.datalake_bucket_name
  dataset_name = var.dataset_name
}

module "iam" {
  source       = "./modules/iam"
  project_id   = var.project_id
  api_sa_name  = "biometric-api-dev-sa"
}

