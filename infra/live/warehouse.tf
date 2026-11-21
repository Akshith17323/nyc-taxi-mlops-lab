# Reference wiring for S1: the Redshift cluster. Output names are fixed by contracts/platform.yaml.

module "warehouse" {
  source            = "../modules/redshift"
  subnet_ids        = data.aws_subnets.default.ids
  availability_zone = var.availability_zone
}

output "redshift_cluster_id" {
  value = module.warehouse.cluster_id
}

output "redshift_database" {
  value = module.warehouse.database
}
