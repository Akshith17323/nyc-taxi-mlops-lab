# S0: wire the root module.
#
# Given modules in ../modules:
#   host    one EC2 host per role in contracts/runtime.yaml (platform, app, llm)
#   rds     Postgres for Dagster, MLflow and pgvector
#   bucket  your artifact bucket (never aws_s3_bucket: see AGENTS.md)
#   secret  the lab/wiki secret container

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_subnets" "primary" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "availability-zone"
    values = [var.availability_zone]
  }
}

module "host_platform" {
  source             = "../modules/host"
  role               = "platform"
  instance_type      = var.platform_instance_type
  subnet_id          = data.aws_subnets.primary.ids[0]
  security_group_ids = [aws_security_group.platform.id]
  elastic_ip         = true
}

module "host_app" {
  source             = "../modules/host"
  role               = "app"
  instance_type      = var.app_instance_type
  subnet_id          = data.aws_subnets.primary.ids[0]
  security_group_ids = [aws_security_group.app.id]
  elastic_ip         = true
}

module "host_llm" {
  source             = "../modules/host"
  role               = "llm"
  instance_type      = var.llm_instance_type
  subnet_id          = data.aws_subnets.primary.ids[0]
  security_group_ids = [aws_security_group.llm.id]
  elastic_ip         = true
}

module "rds" {
  source             = "../modules/rds"
  instance_class     = var.rds_instance_class
  subnet_ids         = data.aws_subnets.default.ids
  security_group_ids = [aws_security_group.rds.id]
}

module "bucket" {
  source = "../modules/bucket"
  name   = "lab-artifact"
}

module "secret_wiki" {
  source      = "../modules/secret"
  name        = "lab/wiki"
  description = "Wiki credentials for RAG"
}

module "secret_grafana" {
  source      = "../modules/secret"
  name        = "lab/grafana"
  description = "Grafana Cloud Prometheus credentials for Alloy"
}
