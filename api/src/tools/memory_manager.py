import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.firestore import get_firestore_client

log = logging.getLogger(__name__)

COLLECTION_NAME = "user_memories"


class SemanticMemoryInput(BaseModel):
    """Input for saving a semantic memory."""

    user_id: str = Field(..., description="The ID of the user.")
    memory_type: Literal["preference", "constraint", "health_quirk", "coaching_style", "other"] = Field(
        ..., description="The category of the memory."
    )
    memory_text: str = Field(..., description="The factual information to remember.")
    source_session_id: str | None = Field(None, description="The chat session ID that generated this memory.")
    confidence_score: float = Field(1.0, description="Confidence in the extraction (0.0 to 1.0).")


@tool("save_semantic_memory", args_schema=SemanticMemoryInput)
def save_semantic_memory(
    user_id: str,
    memory_type: str,
    memory_text: str,
    source_session_id: str | None = None,
    confidence_score: float = 1.0,
) -> str:
    """Saves a 'Golden Nugget' fact about the user to long-term semantic memory.
    Use this when the user states a clear preference, constraint, or recurring health fact.
    """
    db = get_firestore_client()
    doc_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    memory_data = {
        "user_id": user_id,
        "memory_type": memory_type,
        "memory_text": memory_text,
        "source_session_id": source_session_id,
        "confidence_score": confidence_score,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }

    try:
        db.collection(COLLECTION_NAME).document(doc_id).set(memory_data)
        log.info(f"✅ Semantic memory saved: {doc_id} for user {user_id}")
        return f"Successfully saved memory (ID: {doc_id}): {memory_text}"
    except Exception as e:
        log.error(f"❌ Failed to save semantic memory: {e}")
        return f"Error saving memory: {e}"


class UpdateMemoryInput(BaseModel):
    """Input for updating an existing semantic memory."""

    memory_id: str = Field(..., description="The unique ID of the memory to update.")
    new_text: str = Field(..., description="The updated factual information.")


@tool("update_semantic_memory", args_schema=UpdateMemoryInput)
def update_semantic_memory(memory_id: str, new_text: str) -> str:
    """Updates the content of an existing semantic memory.
    Use this when a user contradicts or refines a previously stored fact.
    """
    db = get_firestore_client()
    now = datetime.now(UTC)

    try:
        doc_ref = db.collection(COLLECTION_NAME).document(memory_id)
        doc = doc_ref.get()
        if not doc.exists:
            return f"Error: Memory with ID {memory_id} not found."

        doc_ref.update(
            {
                "memory_text": new_text,
                "updated_at": now,
                "is_active": True,  # Ensure it's active if updated
            }
        )
        log.info(f"✅ Semantic memory updated: {memory_id}")
        return f"Successfully updated memory {memory_id} to: {new_text}"
    except Exception as e:
        log.error(f"❌ Failed to update semantic memory {memory_id}: {e}")
        return f"Error updating memory: {e}"


class RetireMemoryInput(BaseModel):
    """Input for retiring a semantic memory."""

    memory_id: str = Field(..., description="The unique ID of the memory to retire.")


@tool("retire_semantic_memory", args_schema=RetireMemoryInput)
def retire_semantic_memory(memory_id: str) -> str:
    """Soft-deletes a semantic memory by marking it as inactive.
    Use this when a fact is no longer relevant or was saved in error.
    """
    db = get_firestore_client()
    now = datetime.now(UTC)

    try:
        doc_ref = db.collection(COLLECTION_NAME).document(memory_id)
        doc = doc_ref.get()
        if not doc.exists:
            return f"Error: Memory with ID {memory_id} not found."

        doc_ref.update({"is_active": False, "updated_at": now})
        log.info(f"✅ Semantic memory retired: {memory_id}")
        return f"Successfully retired memory {memory_id}."
    except Exception as e:
        log.error(f"❌ Failed to retire semantic memory {memory_id}: {e}")
        return f"Error retiring memory: {e}"
