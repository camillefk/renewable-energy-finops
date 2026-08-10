resource "google_bigquery_dataset" "silver_layer" {
  dataset_id  = var.silver_dataset_name
  project     = var.project_id
  location    = var.region
  description = "Silver Trusted Dataset - Clean and deduplicated data"
}

resource "google_bigquery_dataset" "gold_layer" {
  dataset_id  = var.gold_dataset_name
  project     = var.project_id
  location    = var.region
  description = "Gold Analytical Mart - Aggregated metrics for BI"
}