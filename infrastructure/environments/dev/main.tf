terraform {
  required_version = ">= 1.5.0"
  
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  # Starting with local state for development as requested.
  # This should be migrated to a GCS backend (using the storage module) for production.
  backend "local" {
    path = "terraform.tfstate"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Example module invocation (To be expanded)
# module "network" {
#   source = "../../modules/network"
#   # variables...
# }
