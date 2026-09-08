"""Base abstract interface for multi-tenant biometric storage (GCP vs Local-First)."""

from abc import ABC, abstractmethod
from typing import Any


class StorageEngine(ABC):
    """Abstract interface for multi-tenant biometric storage (GCP vs Local-First)."""

    # --- Profile & User Management ---
    @abstractmethod
    def get_user_profile(self, user_id: str) -> dict[str, Any]:
        """Retrieves user profile from OLTP store."""
        pass

    @abstractmethod
    def update_user_profile(self, user_id: str, data: dict[str, Any]) -> None:
        """Merges updates into user profile in OLTP store."""
        pass

    # --- Goals ---
    @abstractmethod
    def get_user_goals(self, user_id: str) -> list[dict[str, Any]]:
        """Retrieves active user goals."""
        pass

    @abstractmethod
    def save_user_goal(self, user_id: str, goal: dict[str, Any]) -> str:
        """Persists or updates a user goal."""
        pass

    # --- Semantic Memories ---
    @abstractmethod
    def get_semantic_memories(self, user_id: str) -> list[dict[str, Any]]:
        """Retrieves active semantic memory golden nuggets."""
        pass

    @abstractmethod
    def save_semantic_memory(
        self,
        user_id: str,
        memory_text: str,
        memory_type: str = "fact",
        source_session_id: str | None = None,
        confidence_score: float = 1.0,
    ) -> str:
        """Persists a new semantic memory."""
        pass

    @abstractmethod
    def update_semantic_memory(self, memory_id: str, new_text: str) -> str:
        """Updates text of an existing semantic memory."""
        pass

    @abstractmethod
    def retire_semantic_memory(self, memory_id: str) -> str:
        """Deactivates a semantic memory."""
        pass

    # --- Calibration Profile Markers ---
    @abstractmethod
    def get_calibration_markers(self, user_id: str) -> list[dict[str, Any]]:
        """Retrieves PCP calibration markers."""
        pass

    @abstractmethod
    def save_calibration_marker(
        self, user_id: str, marker_type: str, marker_value: float, context: str | None = None
    ) -> str:
        """Saves or updates a calibration marker."""
        pass

    # --- Health Status ---
    @abstractmethod
    def get_health_status(self, user_id: str) -> dict[str, Any] | None:
        """Retrieves latest health status."""
        pass

    @abstractmethod
    def log_health_status(self, user_id: str, health_data: dict[str, Any]) -> str:
        """Logs daily subjective health status."""
        pass

    # --- Analytical Series & Telemetry ---
    @abstractmethod
    def insert_activities(self, user_id: str, activities: list[dict[str, Any]]) -> None:
        """Inserts or merges activity summaries."""
        pass

    @abstractmethod
    def get_recent_activities(
        self,
        user_id: str,
        limit: int = 10,
        offset: int = 0,
        activity_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieves recent activities."""
        pass

    @abstractmethod
    def get_activity_telemetry(self, activity_id: str, _user_id: str | None = None) -> list[dict[str, Any]]:
        """Retrieves 1s telemetry records for an activity."""
        pass

    @abstractmethod
    def get_daily_physiology(self, user_id: str, days: int = 14) -> list[dict[str, Any]]:
        """Retrieves daily physiological metrics (RHR, HRV, Body Battery, Stress)."""
        pass

    @abstractmethod
    def query_macro_load_history(
        self, user_id: str, group_by: str = "weekly", limit_months: int = 6
    ) -> list[dict[str, Any]]:
        """Aggregates weekly or monthly training load."""
        pass

    # --- Vector Search / RAG ---
    @abstractmethod
    def search_knowledge_vectors(self, query_vector: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        """Searches the exercise science knowledge vector store."""
        pass

    # --- API Keys & Multi-Tenant Auth ---
    @abstractmethod
    def validate_api_key(self, api_key: str, user_id: str) -> bool:
        """Validates if an API key is valid for the given user_id."""
        pass

    @abstractmethod
    def create_api_key(self, user_id: str, name: str = "default") -> str:
        """Generates, saves, and returns a new plaintext API key for a user."""
        pass

    @abstractmethod
    def list_users(self) -> list[str]:
        """Retrieves list of active athlete/user IDs."""
        pass
