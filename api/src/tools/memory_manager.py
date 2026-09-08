import logging
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.storage.factory import get_storage_engine

log = logging.getLogger(__name__)


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
    try:
        engine = get_storage_engine()
        doc_id = engine.save_semantic_memory(
            user_id=user_id,
            memory_text=memory_text,
            memory_type=memory_type,
            source_session_id=source_session_id,
            confidence_score=confidence_score,
        )
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
    try:
        engine = get_storage_engine()
        result = engine.update_semantic_memory(memory_id, new_text)
        log.info(f"✅ Semantic memory updated: {memory_id}")
        return result
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
    try:
        engine = get_storage_engine()
        result = engine.retire_semantic_memory(memory_id)
        log.info(f"✅ Semantic memory retired: {memory_id}")
        return result
    except Exception as e:
        log.error(f"❌ Failed to retire semantic memory {memory_id}: {e}")
        return f"Error retiring memory: {e}"
