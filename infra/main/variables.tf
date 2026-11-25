variable "region" {
  description = "AWS region of every resource in this stack."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name, used in resource names and in the Environment tag."
  type        = string
  default     = "dev"

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,9}$", var.environment))
    error_message = "The environment must be 2 to 10 lower-case letters or digits, starting with a letter."
  }
}

# The limits the functions enforce. They are strings because the code reads
# them as decimal text and money is never a float.
variable "max_usd_per_disc" {
  description = "Most that may be spent on one disc, in USD. The value of FAREGUARD_MAX_USD_PER_DISC."
  type        = string
  default     = "1.00"

  validation {
    condition     = can(regex("^[0-9]{1,9}(\\.[0-9]{1,2})?$", var.max_usd_per_disc)) && try(tonumber(var.max_usd_per_disc) > 0, false)
    error_message = "The value must be a positive decimal with at most two decimals, such as 1.00."
  }
}

variable "monthly_cap_usd" {
  description = "Most that may be spent in one calendar month, in USD. The value of FAREGUARD_MONTHLY_CAP_USD."
  type        = string
  default     = "5.00"

  validation {
    condition     = can(regex("^[0-9]{1,9}(\\.[0-9]{1,2})?$", var.monthly_cap_usd)) && try(tonumber(var.monthly_cap_usd) > 0, false)
    error_message = "The value must be a positive decimal with at most two decimals, such as 5.00."
  }
}

variable "usd_per_minute" {
  description = "Price of one started minute of a job, in USD. The value of FAREGUARD_USD_PER_MINUTE."
  type        = string
  default     = "0.02"

  validation {
    condition     = can(regex("^[0-9]{1,9}(\\.[0-9]{1,2})?$", var.usd_per_minute)) && try(tonumber(var.usd_per_minute) > 0, false)
    error_message = "The value must be a positive decimal with at most two decimals, such as 0.02."
  }
}
