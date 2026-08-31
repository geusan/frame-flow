# Frameflow GCP foundation

This Terraform stack provisions the GCP foundation only: private artifact buckets, separated service accounts, required APIs, and PostgreSQL 17 on Cloud SQL. It does not yet deploy Web, API, Temporal Worker, DNS, or a secret manager payload.

## Prerequisites

```bash
gcloud auth application-default login
cp infra/terraform/environments/dev.tfvars.example infra/terraform/environments/dev.tfvars
export TF_VAR_database_password='replace-with-a-generated-secret'
```

## Commands

```bash
make tf-fmt
make tf-validate
make tf-plan TF_ENV=dev
make tf-apply TF_ENV=dev
```

`tf-apply` only accepts the saved plan produced by `tf-plan`. Destruction requires an explicit environment confirmation:

```bash
make tf-destroy TF_ENV=dev CONFIRM_DESTROY=dev
```

Never commit `.tfvars`, plan files, state files, or database passwords. Configure a remote encrypted state backend before using this stack with a team or production environment.
