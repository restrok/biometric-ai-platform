"""Universal embeddings factory supporting FastEmbed (ONNX/ARM friendly), Ollama, Google, and OpenAI-compatible."""

import logging
import os

from langchain_core.embeddings import Embeddings

log = logging.getLogger(__name__)


class FastEmbedWrapper(Embeddings):
    """LangChain-compatible wrapper for FastEmbed ONNX embeddings."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._model = TextEmbedding(model_name=model_name)
        log.info(f"🧠 FastEmbed initialized with model: {model_name}")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in vec] for vec in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return [float(x) for x in next(iter(self._model.embed([text])))]


def get_embeddings_model() -> Embeddings:
    """Returns the appropriate Embeddings model based on EMBEDDINGS_PROVIDER env var.

    Options:
    - 'fastembed' (default for local): Lightweight CPU/ARM-friendly ONNX embeddings.
    - 'ollama': Local Ollama instance (default nomic-embed-text).
    - 'google': Google Generative AI embeddings (gemini-embedding-001).
    - 'openai' / 'custom': OpenAI-compatible endpoint.
    """
    provider = os.getenv("EMBEDDINGS_PROVIDER")
    if not provider:
        storage_mode = os.getenv("STORAGE_MODE", "gcp").lower()
        provider = "fastembed" if storage_mode == "local" else "ollama"

    provider = provider.lower()

    if provider == "fastembed":
        model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
        return FastEmbedWrapper(model_name=model_name)

    if provider == "ollama":
        base_url = os.getenv("EMBEDDING_BASE_URL", "http://localhost:11434/v1")
        model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
        from langchain_openai import OpenAIEmbeddings
        from pydantic import SecretStr

        return OpenAIEmbeddings(
            model=model,
            base_url=base_url,
            api_key=SecretStr("ollama"),
            check_embedding_ctx_length=False,
        )

    if provider == "google":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        model = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")
        return GoogleGenerativeAIEmbeddings(model=model)

    if provider in ("openai", "custom"):
        base_url = os.getenv("EMBEDDING_BASE_URL", "https://api.openai.com/v1")
        model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        api_key = os.getenv("OPENAI_API_KEY", "dummy")
        from langchain_openai import OpenAIEmbeddings
        from pydantic import SecretStr

        return OpenAIEmbeddings(
            model=model,
            base_url=base_url,
            api_key=SecretStr(api_key),
            check_embedding_ctx_length=False,
        )

    log.warning(f"Unknown EMBEDDINGS_PROVIDER '{provider}', falling back to FastEmbed")
    return FastEmbedWrapper()
