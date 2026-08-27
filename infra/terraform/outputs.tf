output "artifact_buckets" { value = { for key, bucket in google_storage_bucket.artifacts : key => bucket.name } }
output "reference_analyzer_service_account" { value = google_service_account.reference_analyzer.email }
output "generation_worker_service_account" { value = google_service_account.generation_worker.email }
output "cloud_sql_connection_name" { value = google_sql_database_instance.postgres.connection_name }

