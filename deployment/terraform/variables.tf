variable "project_id" {
  description = "Target Google Cloud project ID for PathFinder AI deployment."
  type        = string
}

variable "region" {
  description = "Google Cloud region for Cloud Run, Cloud SQL, and Firestore."
  type        = string
  default     = "us-central1"
}

variable "container_image" {
  description = "Artifact Registry container image URI for PathFinder AI."
  type        = string
}

variable "ingress" {
  description = "Cloud Run ingress policy. Use INGRESS_TRAFFIC_ALL with IAM auth + `gcloud run services proxy` for demos, or INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER behind an External LB + IAP."
  type        = string
  default     = "INGRESS_TRAFFIC_ALL"
}
