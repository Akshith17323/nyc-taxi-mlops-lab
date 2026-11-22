# The names are fixed by contracts/runtime.yaml (terraform_outputs).

output "app_public_ip" {
  value = module.app.public_ip
}

output "app_instance_id" {
  value = module.app.instance_id
}

output "platform_instance_id" {
  value = module.platform.instance_id
}

output "llm_instance_id" {
  value = module.llm.instance_id
}

output "rds_endpoint" {
  value = module.rds.endpoint
}

output "artifact_bucket" {
  value = module.artifacts.name
}

# Serving on the app host finds MLflow here (repo variable MLFLOW_TRACKING_URI, stages/S3.md).
# A private IP survives stop and start, so it stays valid across sessions.
output "platform_private_ip" {
  value = module.platform.private_ip
}

