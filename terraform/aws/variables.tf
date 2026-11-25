variable "sandbox_role_name" {
  type        = string
  description = "IAM role sandbox users assume"
}

variable "monthly_limit_usd" {
  type    = number
  default = 500
}

variable "alert_email" {
  type = string
}

variable "reaper_dry_run" {
  type        = bool
  default     = true
  description = "Start true; flip to false after a week of clean logs"
}
