import os
import base64
from pathlib import Path
from dotenv import load_dotenv
from google.cloud import bigquery
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.tools import tool
import logging

log = logging.getLogger(__name__)

# Load and decode API Key (matching main.py logic)
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)
api_key_raw = os.getenv("GOOGLE_API_KEY")

if api_key_raw:
    try:
        decoded_bytes = base64.b64decode(api_key_raw, validate=True)
        decoded_str = decoded_bytes.decode("utf-8")
        if decoded_str.startswith("AIza"):
            os.environ["GOOGLE_API_KEY"] = decoded_str
    except Exception:
        pass

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "bio-intelligence-dev")
DATASET_ID = "biometric_data_dev"
TABLE_ID = "knowledge_base"

@tool
def search_exercise_science(query: str) -> str:
    """
    Searches the internal knowledge base for exercise science principles, 
    training guidelines, and research-backed training methods using BigQuery Vector Search.
    Useful for answering 'why' questions about heart rate zones, recovery, or polarized training.
    """
    client = bigquery.Client(project=PROJECT_ID)
    
    # 1. Generate Embedding for the query
    embeddings_model = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
    query_embedding = embeddings_model.embed_query(query)
    
    # 2. Execute BigQuery Vector Search
    # Note: top_k=3 to stay within context limits
    sql = f"""
    SELECT base.content, distance
    FROM VECTOR_SEARCH(
      TABLE `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`,
      'embedding',
      (SELECT @embedding AS embedding),
      top_k => 3,
      distance_type => 'COSINE'
    )
    """
    
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("embedding", "FLOAT64", query_embedding)
        ]
    )
    
    try:
        query_job = client.query(sql, job_config=job_config)
        results = query_job.result()
        
        context_parts = []
        for row in results:
            context_parts.append(row.content)
            
        if not context_parts:
            return "No specific research found for this query in the knowledge base."
            
        context = "\n---\n".join(context_parts)
        return f"Retrieved Knowledge from BigQuery Exercise Science Base:\n\n{context}"
        
    except Exception as e:
        log.error(f"❌ BigQuery Vector Search failed: {e}")
        return f"Error retrieving exercise science data: {str(e)}"
