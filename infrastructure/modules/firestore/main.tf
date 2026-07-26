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


