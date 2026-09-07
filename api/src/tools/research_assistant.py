import logging
import os

from google.cloud import bigquery
from langchain_core.tools import tool

from src.utils.config import get_config, setup_environment

log = logging.getLogger(__name__)

# Load environment
setup_environment()
config = get_config()

PROJECT_ID = config["project_id"]
DATASET_ID = config["dataset_id"]
TABLE_ID = config["knowledge_base_table"]

if not PROJECT_ID:
    log.error("GOOGLE_CLOUD_PROJECT environment variable is not set. BigQuery tools will fail.")


def get_embeddings_model():
    """Returns local OpenAI-compatible embeddings (nomic-embed-text, 768 dims) if configured, else Google fallback."""
    embedding_base_url = os.getenv("EMBEDDING_BASE_URL", "http://192.168.89.32:11434/v1")
    embedding_model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
    if embedding_base_url:
        from langchain_openai import OpenAIEmbeddings
        from pydantic import SecretStr

        return OpenAIEmbeddings(
            model=embedding_model,
            base_url=embedding_base_url,
            api_key=SecretStr("ollama"),
            check_embedding_ctx_length=False,
        )
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    return GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")


@tool
def search_exercise_science(query: str) -> str:
    """
    Searches the internal knowledge base for exercise science principles,
    training guidelines, and research-backed training methods using BigQuery Vector Search.
    Useful for answering 'why' questions about heart rate zones, recovery, or polarized training.
    """
    client = bigquery.Client(project=PROJECT_ID)

    # 1. Generate Embedding for the query (using local 768-dim embeddings by default)
    embeddings_model = get_embeddings_model()
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
        query_parameters=[bigquery.ArrayQueryParameter("embedding", "FLOAT64", query_embedding)]
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
