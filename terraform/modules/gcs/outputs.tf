output "bucket_name" {
  description = "The name of the provisioned Bronze bucket"
  value       = google_storage_bucket.bronze_layer.name
}