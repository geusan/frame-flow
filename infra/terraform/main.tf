locals {
  name = "frameflow-${var.environment}"
  buckets = {
    reference  = "${var.project_id}-${local.name}-reference-private"
    formats    = "${var.project_id}-${local.name}-derived-formats"
    generation = "${var.project_id}-${local.name}-generation-assets"
    renders    = "${var.project_id}-${local.name}-final-renders"
  }
}

resource "google_project_service" "required" {
  for_each = toset([
    "aiplatform.googleapis.com",
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
    "speech.googleapis.com",
    "texttospeech.googleapis.com"
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_storage_bucket" "artifacts" {
  for_each                    = local.buckets
  name                        = each.value
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  versioning { enabled = true }
  lifecycle_rule {
    condition { age = each.key == "reference" ? 30 : 180 }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }
}

resource "google_service_account" "reference_analyzer" {
  account_id   = "${local.name}-ref-analyzer"
  display_name = "Frameflow reference analyzer"
}

resource "google_service_account" "generation_worker" {
  account_id   = "${local.name}-generation"
  display_name = "Frameflow generation worker"
}

resource "google_storage_bucket_iam_member" "reference_reader" {
  bucket = google_storage_bucket.artifacts["reference"].name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.reference_analyzer.email}"
}

resource "google_storage_bucket_iam_member" "format_writer" {
  bucket = google_storage_bucket.artifacts["formats"].name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.reference_analyzer.email}"
}

# Deliberately no binding grants generation_worker access to the reference bucket.
resource "google_storage_bucket_iam_member" "generation_assets" {
  for_each = toset(["formats", "generation", "renders"])
  bucket   = google_storage_bucket.artifacts[each.key].name
  role     = each.key == "formats" ? "roles/storage.objectViewer" : "roles/storage.objectAdmin"
  member   = "serviceAccount:${google_service_account.generation_worker.email}"
}

resource "google_sql_database_instance" "postgres" {
  name                = "${local.name}-postgres"
  database_version    = "POSTGRES_17"
  region              = var.region
  deletion_protection = true
  settings {
    tier              = "db-custom-2-7680"
    availability_type = var.environment == "prod" ? "REGIONAL" : "ZONAL"
    disk_autoresize   = true
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }
  }
  depends_on = [google_project_service.required]
}

resource "google_sql_database" "frameflow" {
  name     = "frameflow"
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "api" {
  name     = "frameflow_api"
  instance = google_sql_database_instance.postgres.name
  password = var.database_password
}
