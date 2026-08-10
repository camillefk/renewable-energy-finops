provider "google" {
  project = var.project_id
  region  = var.region
}

module "gcs_bronze" {
  source      = "./modules/gcs"
  project_id  = var.project_id
  region      = var.region
  bucket_name = "bronze-raw-data-bucket-${var.project_id}"
}

module "bigquery_layers" {
  source              = "./modules/bigquery"
  project_id          = var.project_id
  region              = var.region
  silver_dataset_name = "silver_trusted_dataset"
  gold_dataset_name   = "golt_analytical_mart"
}

module "iam_roles" {
  source                = "./modules/iam"
  project_id            = var.project_id
  service_account_email = var.service_account_email
}