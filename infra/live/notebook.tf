# S2: wire infra/modules/notebook (the SageMaker notebook) into this root module, let it reach MLflow
# on the platform host (port 5000, runtime.yaml), and output its name as notebook_name.
# Set github_repo in terraform.tfvars: the notebook clones your public repo.

module "notebook" {
  count     = var.github_repo != null ? 1 : 0
  source    = "../modules/notebook"
  subnet_id = data.aws_subnets.default.ids[0]
  repo_url  = "https://github.com/${var.github_repo}.git"
  env = {
    MLFLOW_TRACKING_URI = "http://${module.host_platform.private_ip}:5000"
    REDSHIFT_CLUSTER_ID = module.redshift.cluster_id
    REDSHIFT_DATABASE   = module.redshift.database
    LAB_DATA_BUCKET     = "nst-mlops-2026"
    LAB_ARTIFACT_BUCKET = module.bucket.name
  }
}

resource "aws_vpc_security_group_ingress_rule" "platform_from_notebook" {
  count                        = var.github_repo != null ? 1 : 0
  security_group_id            = aws_security_group.platform.id
  referenced_security_group_id = module.notebook[0].security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5000
  to_port                      = 5000
  description                  = "MLflow from SageMaker notebook"
}
