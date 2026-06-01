import sys
import json
from google.cloud import bigquery

# Append app path to sys.path to import local modules if needed
sys.path.append('/app')

def run_discovery():
    from src.tools.data_scientist import execute_exploratory_query
    
    query = """
    SELECT 
        DATETIME(TIMESTAMP_SECONDS(a.date), 'America/Argentina/Buenos_Aires') as local_time,
        a.name,
        a.type,
        a.avg_hr
    FROM `biometric_data_dev.recent_activities` a
    WHERE a.user_id = 'fsirio'
      AND a.date >= UNIX_SECONDS(TIMESTAMP('2026-05-01'))
    ORDER BY a.date DESC
    """
    
    # Using the tool's invoke method as recommended
    result = execute_exploratory_query.invoke({'sql': query, 'user_id': 'fsirio'})
    print(json.dumps(result))

if __name__ == "__main__":
    run_discovery()
