import logging

from google.cloud import storage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.config import get_config

log = logging.getLogger(__name__)


class ReadReportInput(BaseModel):
    """Input schema for reading a report artifact."""

    gcs_uri: str = Field(..., description="The Signed URL (https://...) or gs:// URI of the report.")


@tool(args_schema=ReadReportInput)
def read_report_artifact(gcs_uri: str) -> str:
    """
    Reads a detailed markdown report from GCS.
    If the report is too large, it truncates the content to protect the LLM context limit.
    """
    import requests

    try:
        if gcs_uri.startswith("http"):
            response = requests.get(gcs_uri)
            response.raise_for_status()
            content = response.text
        elif gcs_uri.startswith("gs://"):
            parts = gcs_uri.replace("gs://", "").split("/", 1)
            if len(parts) != 2:
                return "Invalid gs:// URI."
            bucket_name, blob_name = parts

            config = get_config()
            # Note: Using standard client as this is a sync tool
            client = storage.Client(project=config.get("project_id"))
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            content = blob.download_as_text()
        else:
            return "Unsupported URI format. Provide a gs:// URI or an HTTP Signed URL."

        # Token Limit Protector: 2000 characters limit (~2KB)
        max_length = 2000
        if len(content) > max_length:
            header = content[:max_length]
            return (
                header
                + f"\n\n... [TRUNCATED: Document exceeds {max_length} characters. Context limit protected. Request fragments if needed.]"
            )
        return content
    except Exception as e:
        log.error(f"Failed to read report: {e}")
        return f"Error reading report: {str(e)}"
