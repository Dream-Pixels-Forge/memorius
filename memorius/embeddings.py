"""Embedding providers for memorius — abstracted vector embedding interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar


class EmbeddingProvider(ABC):
    """Abstract embedding provider. Returns normalized float vectors."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts into vectors."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding vector dimension."""
        ...

    @classmethod
    @abstractmethod
    def from_config(cls, config: dict[str, Any]) -> "EmbeddingProvider":
        """Create provider from config dict."""
        ...


class SentenceTransformerProvider(EmbeddingProvider):
    """Local sentence-transformers embeddings (offline, no API key needed)."""

    _model_key: ClassVar[str] = "all-MiniLM-L6-v2"

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None  # lazy load
        self._dim = 384  # all-MiniLM-L6-v2 default

    def _lazy_load(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
            self._dim = self._model.get_sentence_embedding_dimension()
        except ImportError:
            raise ImportError(
                "sentence-transformers not installed. "
                "Install: pip install memorius[local-embeddings]"
            )

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._lazy_load()
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return [emb.tolist() for emb in embeddings]

    @property
    def dimension(self) -> int:
        self._lazy_load()
        return self._dim

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "SentenceTransformerProvider":
        model = config.get("model", cls._model_key)
        return cls(model_name=model)


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI API-based embeddings."""

    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        self._api_key = api_key
        self._model = model
        self._dim = 1536 if "3-small" in model else 3072
        self._client = None

    def _lazy_load(self):
        if self._client is not None:
            return
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=self._api_key)
        except ImportError:
            raise ImportError(
                "openai package not installed. "
                "Install: pip install memorius[openai]"
            )

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._lazy_load()
        resp = self._client.embeddings.create(input=texts, model=self._model)
        # Sort by index to preserve order
        sorted_data = sorted(resp.data, key=lambda d: d.index)
        return [d.embedding for d in sorted_data]

    @property
    def dimension(self) -> int:
        return self._dim

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "OpenAIEmbeddingProvider":
        openai_cfg = config.get("openai", {})
        api_key = openai_cfg.get("api_key", config.get("api_key", ""))
        model = openai_cfg.get("model", config.get("model", "text-embedding-3-small"))
        if not api_key:
            raise ValueError("OpenAI API key required. Set MEMORIUS_OPENAI_API_KEY or OPENAI_API_KEY")
        return cls(api_key=api_key, model=model)


class ChromaDefaultProvider(EmbeddingProvider):
    """ChromaDB's built-in embedding function (ONNX all-MiniLM-L6-v2).
    
    No extra dependencies — ChromaDB ships its own ONNX runtime.
    Auto-downloads the ONNX model on first use if not already present.
    """
    def __init__(self):
        try:
            import chromadb.utils.embedding_functions as ef
        except ImportError:
            raise ImportError(
                "chromadb not installed. Install:\n"
                "  pip install memorius  (includes chromadb)\n"
                "  or: pip install chromadb"
            )
        
        # Auto-download ONNX model if not present
        self._ensure_model_downloaded()
        
        self._fn = ef.DefaultEmbeddingFunction()
        self._dim = 384

    def _ensure_model_downloaded(self):
        """Ensure the ONNX model is downloaded before initializing.

        Non-fatal: if the pre-download fails (e.g. no network), we warn
        and continue — chromadb's DefaultEmbeddingFunction fetches its own
        copy on first use.
        """
        from memorius.model_download import is_model_downloaded, setup_model

        if not is_model_downloaded():
            print("ONNX model not found. Downloading now...")
            if not setup_model():
                print(
                    "Warning: could not pre-download the ONNX model via "
                    "'memorius setup'. chromadb will attempt its own "
                    "download on first use — ensure network access."
                )

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = self._fn(texts)
        return result

    @property
    def dimension(self) -> int:
        return self._dim

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "ChromaDefaultProvider":
        return cls()


class EmbeddingFactory:
    """Create embedding providers from config."""

    _registry: dict[str, type[EmbeddingProvider]] = {
        "chroma-default": ChromaDefaultProvider,
        "sentence-transformers": SentenceTransformerProvider,
        "openai": OpenAIEmbeddingProvider,
    }

    @classmethod
    def create(cls, config: dict[str, Any]) -> EmbeddingProvider:
        provider_name = config.get("provider", "sentence-transformers")
        provider_cls = cls._registry.get(provider_name)
        if provider_cls is None:
            raise ValueError(
                f"Unknown embedding provider: {provider_name}. "
                f"Available: {list(cls._registry.keys())}"
            )
        return provider_cls.from_config(config)

    @classmethod
    def register(cls, name: str, provider_cls: type[EmbeddingProvider]):
        """Register a custom embedding provider."""
        cls._registry[name] = provider_cls
