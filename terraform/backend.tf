terraform {
  backend "gcs" {
    bucket = "renewable-energy-tfstate-peppy-coda-483817-b1"
    prefix = "terraform/state"
  }
}