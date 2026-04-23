import os
from google.cloud import bigquery
from pathlib import Path
from dotenv import load_dotenv

# Load env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "bio-intelligence-dev")
DATASET_ID = "biometric_data_dev"
TABLE_ID = "finops_logs"

def project_monthly_costs():
    print("📈 AI Platform | Monthly Cost Projection Report")
    print("="*50)
    
    client = bigquery.Client(project=PROJECT_ID)
    
    # Query for historical usage
    query = f"""
    SELECT 
        COUNT(*) as total_calls,
        SUM(total_tokens) as total_tokens,
        SUM(cost_usd) as total_cost,
        AVG(latency_ms) as avg_latency,
        MIN(timestamp) as first_log,
        MAX(timestamp) as last_log
    FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
    """
    
    try:
        results = list(client.query(query).result())
        row = results[0]
        
        if not row.total_calls:
            print("⚠️ No logs found yet. Run some queries to see projections.")
            return

        # Calculate duration in days for the logged period
        delta = row.last_log - row.first_log
        days_active = max(delta.days, 1) 
        
        # Projections
        daily_burn = row.total_cost / days_active
        monthly_projection = daily_burn * 30
        
        print(f"🗓️  Period: {row.first_log.strftime('%Y-%m-%d')} to {row.last_log.strftime('%Y-%m-%d')} ({days_active} days)")
        print(f"🤖 Total Calls: {row.total_calls}")
        print(f"🎫 Total Tokens: {row.total_tokens:,}")
        print(f"⏱️  Avg Latency: {row.avg_latency:.0f}ms")
        print("-" * 50)
        print(f"💵 Total Spent:  ${row.total_cost:.6f}")
        print(f"🔥 Daily Burn:   ${daily_burn:.6f}")
        print(f"🔮 Monthly Est:  ${monthly_projection:.2f}")
        
        # Free Tier Threshold Warning
        requests_per_day = row.total_calls / days_active
        print(f"📊 Activity:     {requests_per_day:.1f} req/day")
        if requests_per_day > 10:
            print("🚨 WARNING: You are approaching the 20 req/day Free Tier limit!")
        else:
            print("✅ Status: Safe within Free Tier limits.")

    except Exception as e:
        print(f"❌ Projection Error: {e}")

if __name__ == "__main__":
    project_monthly_costs()
