terraform {
  required_version = ">= 1.6.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  required_apis = [
    "aiplatform.googleapis.com",
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "firestore.googleapis.com",
    "dlp.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudtrace.googleapis.com",
    "logging.googleapis.com",
    "artifactregistry.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.required_apis)
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "pathfinder" {
  location      = var.region
  repository_id = "pathfinder"
  description   = "Container images for PathFinder AI College Application Advisor"
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

resource "google_service_account" "agent_runtime" {
  account_id   = "pathfinder-agent-sa"
  display_name = "PathFinder AI Cloud Run Least-Privilege Runtime SA"
}

resource "google_project_iam_member" "runtime_roles" {
  for_each = toset([
    "roles/aiplatform.user",
    "roles/datastore.user",
    "roles/cloudsql.client",
    "roles/dlp.user",
    "roles/secretmanager.secretAccessor",
    "roles/cloudtrace.agent",
    "roles/logging.logWriter",
  ])
  project    = var.project_id
  role       = each.value
  member     = "serviceAccount:${google_service_account.agent_runtime.email}"
  depends_on = [google_project_service.apis, google_service_account.agent_runtime]
}

resource "random_password" "db_password" {
  length  = 24
  special = false
}

resource "google_sql_database_instance" "session_db" {
  name             = "pathfinder-sessions-pg"
  database_version = "POSTGRES_16"
  region           = var.region
  settings {
    tier = "db-f1-micro"
  }
  deletion_protection = false
  depends_on          = [google_project_service.apis]
}

resource "google_sql_database" "sessions" {
  name     = "pathfinder_sessions"
  instance = google_sql_database_instance.session_db.name
}

resource "google_sql_user" "agent_user" {
  name     = "pathfinder_app"
  instance = google_sql_database_instance.session_db.name
  password = random_password.db_password.result
}

resource "google_secret_manager_secret" "session_db_url" {
  secret_id = "pathfinder-session-db-url"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "session_db_url" {
  secret      = google_secret_manager_secret.session_db_url.id
  secret_data = "postgresql+asyncpg://${google_sql_user.agent_user.name}:${random_password.db_password.result}@/${google_sql_database.sessions.name}?host=/cloudsql/${google_sql_database_instance.session_db.connection_name}"
}

resource "google_secret_manager_secret" "gemini_api_key" {
  secret_id = "pathfinder-gemini-api-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_firestore_database" "student_memory" {
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"
  depends_on  = [google_project_service.apis]
}

resource "google_cloud_run_v2_service" "pathfinder_agent" {
  name     = "pathfinder-college-advisor"
  location = var.region
  ingress  = var.ingress

  template {
    service_account = google_service_account.agent_runtime.email
    timeout         = "300s"

    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.session_db.connection_name]
      }
    }

    containers {
      image = var.container_image
      ports {
        container_port = 8080
      }
      resources {
        cpu_idle = false # Always-allocated CPU so async memory tasks complete post-response.
        limits = {
          cpu    = "2"
          memory = "1Gi"
        }
      }
      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "TRUE"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = "global"
      }
      env {
        name  = "PATHFINDER_FLASH_MODEL"
        value = "gemini-3.8-flash"
      }
      env {
        name  = "PATHFINDER_PRO_MODEL"
        value = "gemini-3.1-pro"
      }
      env {
        name  = "ENABLE_CLOUD_DLP"
        value = "true"
      }
      env {
        name  = "ENABLE_CLOUD_TRACE"
        value = "true"
      }
      env {
        name  = "CAPTURE_MESSAGE_CONTENT"
        value = "false"
      }
      env {
        name  = "MEMORY_BACKEND"
        value = "firestore"
      }
      env {
        name = "SESSION_DB_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.session_db_url.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_project_iam_member.runtime_roles,
    google_secret_manager_secret_version.session_db_url,
    google_firestore_database.student_memory,
  ]
}
