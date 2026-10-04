# infrastructure/

**Purpose:** infrastructure as code (Terraform), container definitions (Docker) and environment definitions (local, development, staging, production per doc 18 s14).

**Source:** doc 19 Step 2 (directory skeleton); doc 18 s1 (Docker, Terraform) and s14 (Deployment).

**Status:** contains the local development stack only (`docker-compose.yml`, `db/initdb/`; see [docs/dev/local-development.md](../docs/dev/local-development.md)). No Terraform, deployment or environment definitions exist yet. Hosting/cloud provider, container registry and CI/CD platform details are undecided (see ADR proposals). Never commit Terraform state or `.tfvars` files (see `.gitignore`). Production changes require human approval.
