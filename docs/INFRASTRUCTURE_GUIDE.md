# Infrastructure as Code (IaC) Guide

> This project uses **Terraform** to manage Google Cloud Platform (GCP) resources, ensuring consistency, repeatability, and a physical separation of data layers (Medallion Architecture).

## Provisioned Resources
1. **GCS Bucket (Bronze Layer):** `bronze-raw-data-bucket` with a 30-day lifecycle rule moving objects to Coldline storage to optimize costs.
2. **BigQuery Datasets (Silver & Gold Layers):**  
    - `silver_trusted_dataset`  
    - `gold_analytical_mart`
3. **IAM Roles:** Specific BigQuery and GCS permissions assigned to the pipelines's Service Account.

## Remote State
The Terraform state (`terraform.tfstate`) is safely stored in a dedicated GCS bucket configured as a remote backend.

## How to Reproduce
To provision the infrastructure from scratch:

1. Authenticate with GCP:
```text
gcloud auth application-default login
```
2. Navigate to the Terraform directory:
```text
cd terraform
```
3. Create a `terraform.tfvars` file with your variables
```text
project_id            = "your-project-id"
region                = "us-central1"
service_account_email = "renewable-energy-sa@your-project-id.iam.gserviceaccount.com"
```
4. Run the Terraform workflow:
```text
terraform init
```
```text
terraform fmt -recursive
```
```text
terraform validate
```
```text
terraform plan
```
```text
terraform apply
```

## How to Destroy
To clean up the sandbox environment and avoid unexpected cloud costs, run:
```text
terraform destroy
```

*(**Note:** The Bronze GCS bucket has `force_destroy = true`, so it will be deleted even if it contains data).*

---

**Built by:** @camillefk  
**Created:** August 2026  
**Last Updated:** August 09, 2026