# S0: security groups and rules.
#
# Decision point: who may reach the app (ingress scope)? Record it in decisions/.
# Traffic between hosts (ports in contracts/runtime.yaml):
#   app -> platform  MLflow
#   app, platform -> llm  chat and embeddings
#   app, platform -> rds  Postgres
# There is no SSH in this lab: use SSM Session Manager for a shell and port forwarding for UIs.

resource "aws_security_group" "app" {
  name        = "lab-app"
  description = "Traefik HTTP ingress and outbound"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP ingress to Traefik"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.ingress_cidrs
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "lab-app", role = "app" }
}

resource "aws_security_group" "platform" {
  name        = "lab-platform"
  description = "Platform host (MLflow, Dagster)"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "MLflow from app host"
    from_port       = 5000
    to_port         = 5000
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "lab-platform", role = "platform" }
}

resource "aws_security_group" "llm" {
  name        = "lab-llm"
  description = "LLM host (chat and embeddings)"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "LLM chat (8080) and embed (8081) from app and platform"
    from_port       = 8080
    to_port         = 8081
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id, aws_security_group.platform.id]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "lab-llm", role = "llm" }
}

resource "aws_security_group" "rds" {
  name        = "lab-rds"
  description = "Postgres RDS for Dagster and MLflow"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "Postgres from platform and app hosts"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.platform.id, aws_security_group.app.id]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "lab-rds", role = "rds" }
}
