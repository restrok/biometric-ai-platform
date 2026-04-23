import argparse
import json
import logging
import uuid
from pathlib import Path

from google.cloud import bigquery
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.utils.config import get_config, setup_environment

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

# Load environment
setup_environment()
config = get_config()

PROJECT_ID = config["project_id"]
DATASET_ID = config["dataset_id"]
TABLE_ID = config["knowledge_base_table"]

if not PROJECT_ID:
    log.error("GOOGLE_CLOUD_PROJECT environment variable is not set. BigQuery tools will fail.")


def upload_knowledge(reset=False, folder="knowledge_base"):
    client = bigquery.Client(project=PROJECT_ID)
    table_ref = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"

    # 1. Ensure Table Exists
    schema = [
        bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("content", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("embedding", "FLOAT64", mode="REPEATED"),
        bigquery.SchemaField("metadata", "STRING", mode="NULLABLE"),
    ]

    table = bigquery.Table(table_ref, schema=schema)
    client.create_table(table, exists_ok=True)
    log.info(f"Target table: {table_ref}")

    # 2. Load and Chunk Documents
    kb_path = Path(__file__).parent.parent.parent / folder
    if not kb_path.exists():
        log.error(f"Folder not found: {kb_path}")
        return

    log.info(f"Loading files from {kb_path}...")
    loader = DirectoryLoader(str(kb_path), glob="**/*.md", loader_cls=TextLoader)
    docs = loader.load()

    if not docs:
        log.warning("No markdown files found.")
        return

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    splits = text_splitter.split_documents(docs)
    log.info(f"Generated {len(splits)} chunks.")

    # 3. Generate Embeddings
    log.info("Generating embeddings via Gemini...")
    embeddings_model = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")

    rows_to_insert = []
    for i, split in enumerate(splits):
        try:
            embedding = embeddings_model.embed_query(split.page_content)
            rows_to_insert.append(
                {
                    "id": str(uuid.uuid4()),
                    "content": split.page_content,
                    "embedding": embedding,
                    "metadata": json.dumps(split.metadata),
                }
            )
            if (i + 1) % 10 == 0:
                log.info(f"Processed {i + 1}/{len(splits)} chunks...")
        except Exception as e:
            log.error(f"Error embedding chunk {i}: {e}")

    # 4. Load into BigQuery
    if rows_to_insert:
        write_disposition = "WRITE_TRUNCATE" if reset else "WRITE_APPEND"
        log.info(f"Uploading {len(rows_to_insert)} rows (Mode: {write_disposition})...")

        job_config = bigquery.LoadJobConfig(
            schema=schema,
            write_disposition=write_disposition,
        )
        job = client.load_table_from_json(rows_to_insert, table_ref, job_config=job_config)
        job.result()
        log.info("✅ Knowledge base sync complete!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload markdown knowledge to BigQuery RAG.")
    parser.add_argument("--reset", action="store_true", help="Wipe existing knowledge before uploading.")
    parser.add_argument("--folder", type=str, default="knowledge_base", help="Folder containing .md files.")
    args = parser.parse_args()

    upload_knowledge(reset=args.reset, folder=args.folder)
