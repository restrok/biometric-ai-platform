/*
# Budget created via gcloud because of local ADC quota project issues in Terraform:
# gcloud billing budgets create --billing-account=018CA1-78622C-D17780 --display-name="POC Budget - $10" --budget-amount=10USD --filter-projects=projects/bio-intelligence-dev --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0,basis=forecasted-spend

resource "google_billing_budget" "budget" {
  billing_account = var.billing_account_id
  display_name    = "POC Budget - $10"

  budget_filter {
    projects = ["projects/${var.project_id}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = "10"
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }
}
*/

# Limit BigQuery query usage to 1024 MiB (1GB) per day to prevent expensive full scans.
resource "google_service_usage_consumer_quota_override" "bq_query_usage" {
  provider       = google-beta
  project        = var.project_id
  service        = "bigquery.googleapis.com"
  metric         = urlencode("bigquery.googleapis.com/quota/query/usage")
  limit          = urlencode("/d/project")
  override_value = "1024" 
  force          = true
}
