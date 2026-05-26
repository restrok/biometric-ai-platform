resource "google_firestore_database" "database" {
  provider                    = google-beta
  project                     = var.project_id
  name                        = "(default)"
  location_id                 = var.region
  type                        = "FIRESTORE_NATIVE"
  concurrency_mode            = "OPTIMISTIC"
  app_engine_integration_mode = "DISABLED"

  # Recomendación: Mantener borrado suave o protección si es crítico, 
  # pero para dev/pago por uso solemos dejarlo flexible.
  delete_protection_state = "DELETE_PROTECTION_DISABLED"
}

# 🛡️ Quota Management to Protect Free Tier
# Firestore Free Tier: 50k reads, 20k writes, 20k deletes per day.
# Caps the usage at 80% of free tier to provide a safety margin.

resource "google_cloud_quotas_quota_preference" "firestore_reads" {
  service              = "firestore.googleapis.com"
  parent               = "projects/${var.project_id}"
  quota_id             = "ReadOperationsPerDay"
  ignore_safety_checks = "QUOTA_DECREASE_PERCENTAGE_TOO_HIGH"
  quota_config {
    preferred_value = 40000
  }
}

resource "google_cloud_quotas_quota_preference" "firestore_writes" {
  service              = "firestore.googleapis.com"
  parent               = "projects/${var.project_id}"
  quota_id             = "WriteOperationsPerDay"
  ignore_safety_checks = "QUOTA_DECREASE_PERCENTAGE_TOO_HIGH"
  quota_config {
    preferred_value = 15000
  }
}
