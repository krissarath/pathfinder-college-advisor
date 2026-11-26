output "cloud_run_url" {
  description = "Authenticated Cloud Run service URL (access safely via `gcloud run services proxy`)."
  value       = google_cloud_run_v2_service.pathfinder_agent.uri
}

output "artifact_registry_repository" {
  description = "Artifact Registry Docker repository path for building and pushing images."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.pathfinder.repository_id}"
}

output "cloud_sql_connection_name" {
  description = "Cloud SQL PostgreSQL instance connection name."
  value       = google_sql_database_instance.session_db.connection_name
}
