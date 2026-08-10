output "bronze_bucket" {
  value = module.gcs_bronze.bucket_name
}

output "silver_dataset" {
  value = module.bigquery_layers.silver_dataset_id
}

output "gold_dataset" {
  value = module.bigquery_layers.gold_dataset_id
}