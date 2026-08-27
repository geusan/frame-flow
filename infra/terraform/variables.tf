variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "asia-northeast3"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "database_password" {
  type      = string
  sensitive = true
}
