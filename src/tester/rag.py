"""Lightweight RAG knowledge base for test generation context (P2).

No external vector DB. Pure Python + numpy:
  - chunk documents (interface docs, requirements, business rules)
  - embed chunks with a hashing-based bag-of-ngrams vector (fast, dependency-free)
  - retrieve top-k by cosine similarity
  - inject into LLM prompts via `build_context()`

For real production, swap the embedder for bge-m3 / text-embedding-3 via
OPENAI-compatible endpoint (see `Embedder` ABC note in code).
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

_WORD_RE = re.compile(r"[A-Za-z\u4e00-\u9fff0-9]+")


@dataclass
class Chunk:
    text: str
    source: str = ""
    metadata: dict = field(default_factory=dict)


def chunk_text(text: str, chunk_size: int = 400, overlap: int = 60) -> list[str]:
    """Split text into overlapping chunks by character (CJK-friendly)."""
    if len(text) <= chunk_size:
        return [text] if text.strip() else []
    step = chunk_size - overlap
    return [text[i : i + chunk_size] for i in range(0, len(text), step) if text[i : i + chunk_size].strip()]


def _ngrams(text: str, n: int = 2) -> list[str]:
    """Character n-grams (works for CJK and latin)."""
    words = _WORD_RE.findall(text.lower())
    flat = "".join(words)
    if len(flat) < n:
        return [flat] if flat else []
    return [flat[i : i + n] for i in range(len(flat) - n + 1)]


class Vectorizer:
    """Hashing bag-of-ngrams vectorizer (dim fixed, no vocabulary needed)."""

    def __init__(self, dim: int = 512, ngram: int = 2):
        self.dim = dim
        self.ngram = ngram

    def vectorize(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for g in _ngrams(text, self.ngram):
            h = int(hashlib.md5(g.encode("utf-8")).hexdigest()[:8], 16)
            vec[h % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class KnowledgeBase:
    """Store chunks with vectors, retrieve by similarity."""

    def __init__(self, dim: int = 512, ngram: int = 2):
        self.vectorizer = Vectorizer(dim, ngram)
        self.chunks: list[Chunk] = []
        self.vectors: list[list[float]] = []

    def add(self, text: str, source: str = "", metadata: dict | None = None) -> int:
        parts = chunk_text(text)
        for p in parts:
            self.chunks.append(Chunk(p, source, metadata or {}))
            self.vectors.append(self.vectorizer.vectorize(p))
        return len(parts)

    def add_document(self, path: str | Path, source: str | None = None) -> int:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"document not found: {p}")
        return self.add(p.read_text(encoding="utf-8", errors="ignore"),
                        source or str(p))

    def search(self, query: str, top_k: int = 3) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        qv = self.vectorizer.vectorize(query)
        scored = [(c, cosine(qv, v)) for c, v in zip(self.chunks, self.vectors, strict=True)]
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:top_k]

    def build_context(self, query: str, top_k: int = 3, max_chars: int = 1500) -> str:
        """RAG context block for LLM prompts."""
        hits = self.search(query, top_k)
        if not hits:
            return ""
        parts = []
        used = 0
        for chunk, score in hits:
            if score <= 0:
                continue
            block = f"[{chunk.source}]\n{chunk.text}"
            if used + len(block) > max_chars:
                break
            parts.append(block)
            used += len(block)
        return "\n\n".join(parts)


def build_kb_from_dir(directory: str | Path, glob_pattern: str = "*.md") -> KnowledgeBase:
    """Load every matching doc in a directory into a KnowledgeBase."""
    kb = KnowledgeBase()
    for p in sorted(Path(directory).glob(glob_pattern)):
        kb.add_document(p)
    return kb
