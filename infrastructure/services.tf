# 🛠️ Habilitación de APIs y Servicios de Google Cloud
# Este archivo asegura que todos los servicios necesarios estén activos en el proyecto.

locals {
  services = [
    "serviceusage.googleapis.com",   # Necesario para cuotas y límites
    "bigquery.googleapis.com",       # Motor de análisis
    "storage.googleapis.com",        # Almacenamiento de artefactos
    "secretmanager.googleapis.com",  # Gestión de llaves y tokens
    "billingbudgets.googleapis.com", # Necesario para las alertas de presupuesto
    "iam.googleapis.com",            # Gestión de identidades y permisos
  ]
}

resource "google_project_service" "enabled_services" {
  for_each = toset(local.services)
  project  = var.project_id
  service  = each.key

  # Recomendación SRE: No deshabilitar servicios al destruir el recurso para evitar
  # interrumpir otros procesos manuales o dependencias ocultas.
  disable_on_destroy = false
}
