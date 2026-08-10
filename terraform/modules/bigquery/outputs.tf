output "silver_dataset_id" {
  value = google_bigquery_dataset.silver_layer.dataset_id
}

output "gold_dataset_id" {
  value = google_bigquery_dataset.gold_layer.dataset_id
}