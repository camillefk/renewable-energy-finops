variable "project_id" {
  description = "The ID of the GCP Project"
  type        = string
}

variable "region" {
  description = "Region for the BigQuery datasets"
  type        = string
}

variable "silver_dataset_name" {
  description = "Name of the Silver layer dataset"
  type        = string
}

variable "gold_dataset_name" {
  description = "Name of the Gold layer dataset"
  type        = string
}
