variable "project_id" {
  description = "The ID of the GCP project_id"
  type        = string
}

variable "region" {
  description = "The region for the GCS bucket"
  type        = string
}

variable "bucket_name" {
  description = "Name of the Bronze Layer GCS Bucket"
  type        = string
}